import mimetypes
from django.utils.text import slugify

import logging
import socket
from django.shortcuts import render, redirect, get_object_or_404
from django.views.generic import FormView, DetailView, ListView, View
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib import messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.http import HttpResponseRedirect, Http404, HttpResponse
from django.urls import reverse
from verification.tasks import generate_certificate_pdf
from payments.services import check_user_entitlement, consume_user_entitlement, initialize_service_checkout
from verification.models import VerificationRequest, VerificationResult, VerificationDocument
from reports.models import AuditLog
from verification.forms import (
    VerificationRequestCreateForm,
    OfficerResolutionForm,
    OfficerRejectionForm,
)
from verification.services import (
    create_verification_request,
    claim_verification_request,
    complete_verification_request,
    reject_verification_request,
)

from django.contrib.auth.decorators import login_required
from verification.models import VerificationCertificate, CertificateQueryLog
from verification.forms import CertificateApplyForm

from verification.services import (
    create_trustpass_certificate_application,
    issue_verification_certificate,
    get_certificate_pdf_url,
    initialize_certificate_query_transaction,
    log_certificate_query,
    generate_certificate_pdf_bytes
)
from core.permissions import officer_required, is_verification_officer, get_user_home_url, is_employer
from core.rate_limiting import get_client_ip
from reports.models import FraudReport
from payments.models import Transaction, SiteSettings
        
logger = logging.getLogger(__name__)


def can_view_verification(user, req: VerificationRequest) -> bool:
    """
    Least-privilege authorization check:
    - Requester (user == req.requester)
    - Authorized Verification Officer (user.role == 'officer')
    - Explicit superuser / administrator
    All other users (including regular staff or unrelated members) are denied.
    """
    if not user or not user.is_authenticated:
        return False
    if user.is_superuser:
        return True
    if is_verification_officer(user):
        return True
    if req.requester_id and req.requester_id == user.id:
        return True
    return False


class VerificationListView(LoginRequiredMixin, ListView):
    """Lists requests submitted by the logged-in user."""
    model = VerificationRequest
    template_name = 'verification/request_list.html'
    context_object_name = 'requests'
    paginate_by = 15

    def get_queryset(self):
        return (
            VerificationRequest.objects.filter(requester=self.request.user)
            .select_related('target_subject')
            .order_by('-created_at')
        )
    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        base_qs = VerificationRequest.objects.filter(requester=self.request.user)
        ctx['completed_count'] = base_qs.filter(status='completed').count()
        ctx['in_progress_count'] = base_qs.filter(status='in_progress').count()
        ctx['pending_count'] = base_qs.filter(status='pending').count()
        return ctx


class VerificationCreateView(LoginRequiredMixin, FormView):
    """Allows authenticated users to request an identity or background verification."""
    form_class = VerificationRequestCreateForm
    template_name = 'verification/request_form.html'

    def dispatch(self, request, *args, **kwargs):
        if request.user.is_authenticated:
            allowed, reason, details = check_user_entitlement(request.user, service='verification')
            if not allowed and reason == 'service_restricted':
                messages.error(
                    request,
                    details.get('message', "Access to Identity Verification has been restricted for your account by platform administration.")
                )
                return redirect(get_user_home_url(request.user))
        return super().dispatch(request, *args, **kwargs)

    def get_initial(self):
        initial = super().get_initial()
        req_type = self.request.GET.get('type')
        if req_type and req_type in dict(VerificationRequest.VERIFICATION_TYPES):
            initial['verification_type'] = req_type
        return initial

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        from payments.models import SiteSettings, Transaction
        from payments.services import get_user_prepaid_balance
        site_settings = SiteSettings.get()
        allowed, _, _ = check_user_entitlement(self.request.user, service='verification')
        user_balance = get_user_prepaid_balance(self.request.user)

        paid_ref = self.request.GET.get('paid_ref') or self.request.POST.get('paid_ref')
        paid_tx = None
        if paid_ref:
            paid_tx = Transaction.objects.filter(
                reference=paid_ref,
                user=self.request.user,
                status='success',
                is_active=True,
            ).first()

        ctx['user_balance'] = user_balance
        ctx['has_balance'] = user_balance >= site_settings.price_verification_basic
        if user_balance >= site_settings.price_verification_basic or paid_tx:
            ctx['has_entitlement'] = True
            if paid_tx:
                ctx['prepaid_reference'] = paid_ref
                ctx['prepaid_amount'] = paid_tx.amount_naira
                ctx['is_comprehensive_prepaid'] = paid_tx.amount_kobo >= (site_settings.price_verification_business * 100)
            elif user_balance >= site_settings.price_verification_business:
                ctx['is_comprehensive_prepaid'] = True

        if 'has_entitlement' not in ctx:
            ctx['has_entitlement'] = allowed
        ctx['price_basic'] = site_settings.price_verification_basic
        ctx['price_business'] = site_settings.price_verification_business
        return ctx

    def form_valid(self, form):
        allowed, reason, details = check_user_entitlement(self.request.user, service='verification')
        if not allowed and reason == 'service_restricted':
            messages.error(self.request, details.get('message', "Your account has been restricted from requesting verifications."))
            return redirect(get_user_home_url(self.request.user))

        ip_addr = get_client_ip(self.request)
        try:
            docs = form.cleaned_data.get('documents') or self.request.FILES.getlist('document')
            verification_type = form.cleaned_data['verification_type']
            from payments.models import SiteSettings, Transaction
            from payments.services import get_user_prepaid_balance, deduct_user_prepaid_balance, get_topup_difference, initialize_service_checkout
            st_settings = SiteSettings.get()
            high_tier = ('business', 'business_cac', 'cac', 'corporate', 'full_check', 'property', 'vehicle', 'contract')
            req_price = st_settings.price_verification_business if verification_type in high_tier else st_settings.price_verification_basic
            user_balance = get_user_prepaid_balance(self.request.user)

            # Check for direct pre-paid reference in URL/POST
            paid_ref = self.request.GET.get('paid_ref') or self.request.POST.get('paid_ref')
            has_valid_prepayment = False
            paid_tx = None
            if paid_ref:
                paid_tx = Transaction.objects.filter(
                    reference=paid_ref,
                    user=self.request.user,
                    status='success',
                    is_active=True,
                ).first()
                if paid_tx and paid_tx.amount_kobo >= (req_price * 100):
                    has_valid_prepayment = True

            if allowed:
                # Subscription entitlement
                verif_request = create_verification_request(
                    requester=self.request.user,
                    subject_name=form.cleaned_data['subject_name'],
                    subject_type=form.cleaned_data['subject_type'],
                    verification_type=verification_type,
                    notes=form.cleaned_data.get('notes', ''),
                    identifier_type=form.cleaned_data.get('identifier_type') or None,
                    identifier_value=form.cleaned_data.get('identifier_value') or None,
                    ip_address=ip_addr,
                    documents=docs,
                    status='pending',
                )
                consume_user_entitlement(self.request.user, service='verification')
                messages.success(
                    self.request,
                    f"Verification request [{verif_request.reference_number}] submitted successfully using plan quota."
                )
                return redirect('verification:detail', reference_number=verif_request.reference_number)

            elif has_valid_prepayment and paid_tx:
                # Direct pre-paid transaction reference
                paid_tx.is_active = False
                paid_tx.save(update_fields=['is_active'])
                notes = form.cleaned_data.get('notes', '')
                if paid_tx.amount_kobo >= (st_settings.price_verification_business * 100):
                    tier_note = "[Pre-paid: Comprehensive Due Diligence Tier (₦3,500)]"
                    notes = f"{tier_note}\n{notes}".strip() if notes else tier_note

                verif_request = create_verification_request(
                    requester=self.request.user,
                    subject_name=form.cleaned_data['subject_name'],
                    subject_type=form.cleaned_data['subject_type'],
                    verification_type=verification_type,
                    notes=notes,
                    identifier_type=form.cleaned_data.get('identifier_type') or None,
                    identifier_value=form.cleaned_data.get('identifier_value') or None,
                    ip_address=ip_addr,
                    documents=docs,
                    status='pending',
                )
                messages.success(
                    self.request,
                    f"Verification request [{verif_request.reference_number}] submitted successfully using pre-paid order {paid_ref}."
                )
                return redirect('verification:detail', reference_number=verif_request.reference_number)

            elif user_balance >= req_price:
                # Dynamic account balance deduction!
                ok, rem_bal = deduct_user_prepaid_balance(self.request.user, req_price, f"Verification: {verification_type}")
                notes = form.cleaned_data.get('notes', '')
                if req_price >= st_settings.price_verification_business:
                    tier_note = f"[Comprehensive Due Diligence Tier (₦{req_price:,.0f})]"
                    notes = f"{tier_note}\n{notes}".strip() if notes else tier_note

                verif_request = create_verification_request(
                    requester=self.request.user,
                    subject_name=form.cleaned_data['subject_name'],
                    subject_type=form.cleaned_data['subject_type'],
                    verification_type=verification_type,
                    notes=notes,
                    identifier_type=form.cleaned_data.get('identifier_type') or None,
                    identifier_value=form.cleaned_data.get('identifier_value') or None,
                    ip_address=ip_addr,
                    documents=docs,
                    status='pending',
                )
                messages.success(
                    self.request,
                    f"Verification request [{verif_request.reference_number}] submitted successfully! ₦{req_price:,.0f} paid from your balance (₦{rem_bal:,.0f} remaining)."
                )
                return redirect('verification:detail', reference_number=verif_request.reference_number)

            else:
                # Insufficient balance or no payment: top up difference or full price
                topup_needed = get_topup_difference(user_balance, req_price)
                action = self.request.POST.get('action', 'submit')
                if action != 'payg':
                    ctx = self.get_context_data(form=form)
                    ctx['quota_exceeded'] = True
                    ctx['selected_price'] = req_price
                    ctx['user_balance'] = user_balance
                    ctx['topup_needed'] = topup_needed
                    ctx['verification_type'] = verification_type
                    return self.render_to_response(ctx)

                # Initialize Paystack checkout for topup_needed
                service_key = 'business_verification' if verification_type in high_tier else 'verification'
                tier_slug = 'business' if verification_type in high_tier else 'basic'
                verif_request = create_verification_request(
                    requester=self.request.user,
                    subject_name=form.cleaned_data['subject_name'],
                    subject_type=form.cleaned_data['subject_type'],
                    verification_type=verification_type,
                    notes=form.cleaned_data.get('notes', ''),
                    identifier_type=form.cleaned_data.get('identifier_type') or None,
                    identifier_value=form.cleaned_data.get('identifier_value') or None,
                    ip_address=ip_addr,
                    documents=docs,
                    status='pending_payment',
                )
                if user_balance > 0:
                    deduct_user_prepaid_balance(self.request.user, user_balance, f"Partial top-up for {verif_request.reference_number}")

                try:
                    checkout_data = initialize_service_checkout(
                        user=self.request.user,
                        service=service_key,
                        tier=tier_slug,
                        amount_naira=topup_needed,
                        metadata={
                            'verification_reference': verif_request.reference_number,
                            'service': service_key,
                        }
                    )
                    self.request.session['vng_pending_ref'] = checkout_data['reference']
                    return redirect(checkout_data['authorization_url'])
                except Exception as exc:
                    logger.exception("Failed to initialize verification checkout: %s", exc)
                    ctx = self.get_context_data(form=form)
                    ctx['quota_exceeded'] = True
                    ctx['selected_price'] = topup_needed
                    ctx['gateway_error'] = str(exc)
                    return self.render_to_response(ctx)
        
        except ValidationError as e:
            form.add_error(None, e.message if hasattr(e, 'message') else str(e))
            return self.form_invalid(form)


class VerificationDetailView(LoginRequiredMixin, DetailView):
    """
    Least-privilege object-level access view for request details and findings.
    """
    model = VerificationRequest
    template_name = 'verification/request_detail.html'
    context_object_name = 'verification_request'

    def get_object(self, queryset=None):
        ref = self.kwargs.get('reference_number')
        obj = get_object_or_404(
            VerificationRequest.objects.select_related('target_subject', 'requester').prefetch_related('result', 'documents'),
            reference_number=ref
        )
        if not can_view_verification(self.request.user, obj):
            raise PermissionDenied("You do not have authorization to view this verification record.")

        # Ensure VerificationResult exists if status is completed
        if obj.status == 'completed' and not hasattr(obj, 'result'):
            VerificationResult.objects.get_or_create(
                request=obj,
                defaults={
                    'outcome': 'verified',
                    'summary': obj.notes or 'Official verification confirmed and approved.',
                    'verified_by': self.request.user if (self.request.user.is_superuser or is_verification_officer(self.request.user)) else None,
                    'verified_at': obj.updated_at or timezone.now(),
                    'details': {}
                }
            )
            obj.refresh_from_db()
        return obj

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['is_officer'] = is_verification_officer(self.request.user) or self.request.user.is_superuser
        if ctx['is_officer']:
            ctx['resolution_form'] = OfficerResolutionForm()
            ctx['rejection_form'] = OfficerRejectionForm()
        return ctx


class OfficerQueueView(LoginRequiredMixin, ListView):
    """
    Verification Officer review desk queue.
    Restricted strictly to users with role 'officer' or superusers.
    """
    model = VerificationRequest
    template_name = 'verification/officer_queue.html'
    context_object_name = 'requests'
    paginate_by = 25

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return self.handle_no_permission()
        if not (is_verification_officer(request.user) or request.user.is_superuser):
            raise PermissionDenied("Access restricted to authorized Verification Officers.")
        return super().dispatch(request, *args, **kwargs)

    def get_queryset(self):
        return (
            VerificationRequest.objects.filter(status__in=['pending', 'in_progress'])
            .select_related('target_subject', 'requester')
            .order_by('status', 'created_at')
        )


class OfficerClaimView(LoginRequiredMixin, View):
    """POST-only action for an officer to claim a pending request."""
    def post(self, request, reference_number):
        if not (is_verification_officer(request.user) or request.user.is_superuser):
            raise PermissionDenied("Verification Officer authorization required.")
        ip_addr = get_client_ip(request)
        try:
            claim_verification_request(reference_number, request.user, ip_address=ip_addr)
            messages.success(request, f"Request [{reference_number}] claimed successfully.")
        except ValidationError as e:
            messages.error(request, str(e))
        return redirect('verification:detail', reference_number=reference_number)


class OfficerResolveView(LoginRequiredMixin, View):
    """POST-only action to complete or reject an in-progress verification."""
    def post(self, request, reference_number):
        if not (is_verification_officer(request.user) or request.user.is_superuser):
            raise PermissionDenied("Verification Officer authorization required.")

        action = request.POST.get('action')
        ip_addr = get_client_ip(request)

        if action == 'complete':
            form = OfficerResolutionForm(request.POST)
            if form.is_valid():
                try:
                    details_data = form.cleaned_data.get('details_dict') or form.cleaned_data.get('details_json') or {}
                    complete_verification_request(
                        reference_number=reference_number,
                        officer_user=request.user,
                        outcome=form.cleaned_data['outcome'],
                        summary=form.cleaned_data['summary'],
                        details=details_data,
                        ip_address=ip_addr
                    )
                    messages.success(request, f"Verification [{reference_number}] marked completed.")
                except ValidationError as e:
                    messages.error(request, str(e))
            else:
                for field, errs in form.errors.items():
                    messages.error(request, f"{field}: {', '.join(errs)}")

        elif action == 'reject':
            form = OfficerRejectionForm(request.POST)
            if form.is_valid():
                try:
                    reject_verification_request(
                        reference_number=reference_number,
                        officer_user=request.user,
                        reason=form.cleaned_data['reason'],
                        ip_address=ip_addr
                    )
                    messages.warning(request, f"Verification [{reference_number}] has been declined.")
                except ValidationError as e:
                    messages.error(request, str(e))
            else:
                for field, errs in form.errors.items():
                    messages.error(request, f"{field}: {', '.join(errs)}")
        else:
            messages.error(request, "Invalid resolution action requested.")

        return redirect('verification:detail', reference_number=reference_number)


# Whitelist of approved, safe factual indicator keys for the public verification report
APPROVED_REPORT_DETAIL_KEYS = {
    'registry_status',
    'registration_number',
    'registration_date',
    'tax_id_status',
    'address_status',
    'employment_status',
    'institution_status',
    'findings_category',
    'verified_source',
    'registry_checked',
    'registration_ref',
    'confirmed_owner',
    'record_status',
    'officer_advisory',
    'inspection_date',
}


class VerificationReportDocumentView(LoginRequiredMixin, DetailView):
    """
    Renders the official printable VerifyNG Verification Report.
    Strictly restricted under least-privilege access to:
    - Original Requester
    - Verification Officers (role='officer')
    - Explicit superusers
    
    Enforces that request.status == 'completed' and a VerificationResult exists.
    Logs an AuditLog entry ('VERIFICATION_REPORT_ACCESSED') upon successful access in get().
    """
    model = VerificationRequest
    template_name = 'verification/report_document.html'
    context_object_name = 'verification_request'

    def get_object(self, queryset=None):
        ref = self.kwargs.get('reference_number')
        obj = get_object_or_404(
            VerificationRequest.objects.select_related(
                'target_subject',
                'requester',
                'result',
                'result__verified_by'
            ),
            reference_number=ref
        )

        # 1. Least-privilege authorization check: Requester, Officer, or Superuser ONLY
        if not can_view_verification(self.request.user, obj):
            raise PermissionDenied("You do not have authorization to access this verification report.")

        # 2. Status gate: Report only exists for completed verifications with a recorded result
        if obj.status != 'completed' or not hasattr(obj, 'result') or obj.result is None:
            raise Http404("Official verification report is only generated for completed verifications.")

        return obj

    def get(self, request, *args, **kwargs):
        # Resolve object: authorization and status checks must succeed first
        self.object = self.get_object()

        # Single-point audit logging executed only after access and readiness are verified
        ip_addr = get_client_ip(request)
        AuditLog.objects.create(
            report=None,
            action="VERIFICATION_REPORT_ACCESSED",
            performed_by=request.user,
            ip_address=ip_addr,
            details={
                "verification_reference": self.object.reference_number,
                "outcome": self.object.result.outcome,
            }
        )

        context = self.get_context_data(object=self.object)
        return self.render_to_response(context)

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        result = self.object.result

        # Filter structured details against the approved whitelist only
        safe_details = {}
        if isinstance(result.details, dict):
            for k, v in result.details.items():
                clean_key = str(k).strip().lower()
                if clean_key in APPROVED_REPORT_DETAIL_KEYS and v is not None:
                    label = clean_key.replace('_', ' ').title()
                    safe_details[label] = str(v).strip()

        ctx['safe_details'] = safe_details
        return ctx



# ============================================================
# W-08: Certificate views
# ============================================================

class CertificateApplyView(LoginRequiredMixin, View):
    """
    Multi-step TrustPass Background Clearance application wizard (DBS-style).
    Applicants apply directly for their employment or enhanced clearance certificate.
    Supports both active subscription quota and direct Paystack Pay-As-You-Go checkout.
    """
    template_name = 'verification/certificate_apply.html'

    def get(self, request):
        allowed, reason, details = check_user_entitlement(request.user, service='certificate')
        if not allowed and reason == 'service_restricted':
            messages.error(
                request,
                details.get('message', "Your account has been restricted from applying for TrustPass certificates by platform administration.")
            )
            return redirect(get_user_home_url(request.user))

        site_settings = SiteSettings.get()
        user = request.user
        from payments.services import get_user_prepaid_balance
        user_balance = get_user_prepaid_balance(request.user)
        paid_ref = request.GET.get('paid_ref')
        paid_tx = None
        if paid_ref:
            from payments.models import Transaction
            paid_tx = Transaction.objects.filter(
                reference=paid_ref,
                user=request.user,
                status='success',
                is_active=True,
            ).first()

        has_coverage = allowed or (user_balance >= site_settings.price_trustpass_1yr) or (paid_tx is not None)

        initial = {
            'full_name': user.get_full_name().strip() or user.username,
            'email': user.email or '',
            'check_level': request.GET.get('level', 'employment'),
        }
        form = CertificateApplyForm(initial=initial)
        context = {
            'form': form,
            'has_entitlement': has_coverage,
            'user_balance': user_balance,
            'prepaid_reference': paid_ref if paid_tx else None,
            'entitlement_details': details,
            'price_trustpass_1yr': site_settings.price_trustpass_1yr,
            'price_trustpass_3yr': site_settings.price_trustpass_3yr,
        }
        return render(request, self.template_name, context)

    def post(self, request):
        allowed, reason, details = check_user_entitlement(request.user, service='certificate')
        if not allowed and reason == 'service_restricted':
            messages.error(
                request,
                details.get('message', "Your account has been restricted from applying for TrustPass certificates by platform administration.")
            )
            return redirect(get_user_home_url(request.user))

        form = CertificateApplyForm(request.POST, request.FILES)
        site_settings = SiteSettings.get()
        from payments.services import get_user_prepaid_balance, deduct_user_prepaid_balance, get_topup_difference, initialize_service_checkout
        user_balance = get_user_prepaid_balance(request.user)

        if not form.is_valid():
            messages.error(request, "Please review and correct the errors indicated on the form.")
            context = {
                'form': form,
                'has_entitlement': allowed or (user_balance >= site_settings.price_trustpass_1yr),
                'user_balance': user_balance,
                'entitlement_details': details,
                'price_trustpass_1yr': site_settings.price_trustpass_1yr,
                'price_trustpass_3yr': site_settings.price_trustpass_3yr,
            }
            return render(request, self.template_name, context)

        cd = form.cleaned_data
        ip_addr = get_client_ip(request)
        tier_choice = cd.get('check_level') or cd.get('certificate_type') or 'employment'
        tier_slug = 'enhanced' if tier_choice == 'enhanced' else 'standard'
        req_price = site_settings.get_service_price('certificate', tier_slug)

        # Check for direct pre-paid Paystack reference
        paid_ref = request.GET.get('paid_ref') or request.POST.get('paid_ref')
        has_valid_prepayment = False
        paid_tx = None
        if paid_ref:
            from payments.models import Transaction
            paid_tx = Transaction.objects.filter(
                reference=paid_ref,
                user=request.user,
                status='success',
                is_active=True,
            ).first()
            if paid_tx and paid_tx.amount_kobo >= (req_price * 100):
                has_valid_prepayment = True

        context = {
            'form': form,
            'has_entitlement': allowed or has_valid_prepayment or (user_balance >= req_price),
            'user_balance': user_balance,
            'prepaid_reference': paid_ref if has_valid_prepayment else None,
            'entitlement_details': details,
            'price_trustpass_1yr': site_settings.price_trustpass_1yr,
            'price_trustpass_3yr': site_settings.price_trustpass_3yr,
        }

        try:
            if allowed:
                # Subscription quota
                certificate = create_trustpass_certificate_application(
                    holder=request.user,
                    full_name=cd['full_name'],
                    check_level=tier_choice,
                    date_of_birth=cd.get('date_of_birth'),
                    gender=cd.get('gender', ''),
                    phone_number=cd.get('phone_number', ''),
                    email=cd.get('email', ''),
                    nin=cd.get('nin', ''),
                    id_document_type=cd.get('id_document_type', ''),
                    id_document_file=cd.get('id_document_file'),
                    employer_name=cd.get('employer_name', ''),
                    job_role=cd.get('job_role', ''),
                    residential_state=cd.get('residential_state', ''),
                    residential_city=cd.get('residential_city', ''),
                    residential_address=cd.get('residential_address') or cd.get('contact_address') or '',
                    ip_address=ip_addr,
                    status='pending',
                )
                consume_user_entitlement(request.user, service='certificate')
                messages.success(
                    request,
                    f"Your TrustPass Clearance Application [{certificate.certificate_id}] has been submitted successfully using plan quota."
                )
                return redirect('verification:my_certificate', certificate_id=certificate.certificate_id)

            elif has_valid_prepayment and paid_tx:
                # Direct pre-paid reference
                paid_tx.is_active = False
                paid_tx.save(update_fields=['is_active'])
                certificate = create_trustpass_certificate_application(
                    holder=request.user,
                    full_name=cd['full_name'],
                    check_level=tier_choice,
                    date_of_birth=cd.get('date_of_birth'),
                    gender=cd.get('gender', ''),
                    phone_number=cd.get('phone_number', ''),
                    email=cd.get('email', ''),
                    nin=cd.get('nin', ''),
                    id_document_type=cd.get('id_document_type', ''),
                    id_document_file=cd.get('id_document_file'),
                    employer_name=cd.get('employer_name', ''),
                    job_role=cd.get('job_role', ''),
                    residential_state=cd.get('residential_state', ''),
                    residential_city=cd.get('residential_city', ''),
                    residential_address=cd.get('residential_address') or cd.get('contact_address') or '',
                    ip_address=ip_addr,
                    status='pending',
                )
                messages.success(
                    request,
                    f"Your TrustPass Clearance Application [{certificate.certificate_id}] has been submitted successfully using pre-paid order {paid_ref}."
                )
                return redirect('verification:my_certificate', certificate_id=certificate.certificate_id)

            elif user_balance >= req_price:
                # Deduct from dynamic account balance!
                ok, rem_bal = deduct_user_prepaid_balance(request.user, req_price, f"TrustPass: {tier_choice}")
                certificate = create_trustpass_certificate_application(
                    holder=request.user,
                    full_name=cd['full_name'],
                    check_level=tier_choice,
                    date_of_birth=cd.get('date_of_birth'),
                    gender=cd.get('gender', ''),
                    phone_number=cd.get('phone_number', ''),
                    email=cd.get('email', ''),
                    nin=cd.get('nin', ''),
                    id_document_type=cd.get('id_document_type', ''),
                    id_document_file=cd.get('id_document_file'),
                    employer_name=cd.get('employer_name', ''),
                    job_role=cd.get('job_role', ''),
                    residential_state=cd.get('residential_state', ''),
                    residential_city=cd.get('residential_city', ''),
                    residential_address=cd.get('residential_address') or cd.get('contact_address') or '',
                    ip_address=ip_addr,
                    status='pending',
                )
                messages.success(
                    request,
                    f"Your TrustPass Clearance Application [{certificate.certificate_id}] has been submitted successfully! ₦{req_price:,.0f} paid from your balance (₦{rem_bal:,.0f} remaining)."
                )
                return redirect('verification:my_certificate', certificate_id=certificate.certificate_id)

            else:
                # Top up difference or pay full amount via Paystack
                topup_amt = get_topup_difference(user_balance, req_price)
                certificate = create_trustpass_certificate_application(
                    holder=request.user,
                    full_name=cd['full_name'],
                    check_level=tier_choice,
                    date_of_birth=cd.get('date_of_birth'),
                    gender=cd.get('gender', ''),
                    phone_number=cd.get('phone_number', ''),
                    email=cd.get('email', ''),
                    nin=cd.get('nin', ''),
                    id_document_type=cd.get('id_document_type', ''),
                    id_document_file=cd.get('id_document_file'),
                    employer_name=cd.get('employer_name', ''),
                    job_role=cd.get('job_role', ''),
                    residential_state=cd.get('residential_state', ''),
                    residential_city=cd.get('residential_city', ''),
                    residential_address=cd.get('residential_address') or cd.get('contact_address') or '',
                    ip_address=ip_addr,
                    status='pending_payment',
                )
                if user_balance > 0:
                    deduct_user_prepaid_balance(request.user, user_balance, f"Partial top-up for certificate {certificate.certificate_id}")

                checkout_data = initialize_service_checkout(
                    user=request.user,
                    service='certificate',
                    tier=tier_slug,
                    amount_naira=topup_amt,
                    metadata={
                        'certificate_id': certificate.certificate_id,
                        'check_level': tier_choice,
                    }
                )
                request.session['vng_pending_ref'] = checkout_data['reference']
                return redirect(checkout_data['authorization_url'])

        except ValidationError as e:
            err_msg = e.message if hasattr(e, 'message') else str(e)
            messages.error(request, err_msg)
            form.add_error(None, err_msg)
            return render(request, self.template_name, context)
        except Exception as exc:
            logger.exception("Failed to process TrustPass application: %s", exc)
            err_msg = f"Application could not be initialized: {exc}"
            messages.error(request, err_msg)
            form.add_error(None, err_msg)
            return render(request, self.template_name, context)


class MyCertificateView(LoginRequiredMixin, DetailView):
    """
    Displays a certificate to the holder (requester).
    Generates a time-limited signed PDF URL via Cloudinary.

    Access: Original requester, verification officers, superusers.
    """
    model = VerificationCertificate
    template_name = 'verification/my_certificate.html'
    context_object_name = 'certificate'

    def get_object(self, queryset=None):
        cert_id = self.kwargs.get('certificate_id')
        obj = get_object_or_404(
            VerificationCertificate.objects.select_related('subject', 'holder'),
            certificate_id=cert_id
        )
        if (
            not self.request.user.is_superuser
            and not is_verification_officer(self.request.user)
            and (obj.holder is None or obj.holder.id != self.request.user.id)
        ):
            raise PermissionDenied("You do not have authorization to view this certificate.")
        return obj

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['pdf_url'] = get_certificate_pdf_url(self.object)
        ctx['is_valid'] = self.object.is_valid
        ctx['is_officer'] = (
            is_verification_officer(self.request.user)
            or self.request.user.is_superuser
        )
        return ctx


class CertificateDownloadPDFView(LoginRequiredMixin, View):
    """
    Directly streams the official Certificate PDF for the requester, candidate, or officer.
    """
    def get(self, request, certificate_id):
        cert = get_object_or_404(
            VerificationCertificate.objects.select_related('subject', 'holder'),
            certificate_id=certificate_id
        )
        if not (request.user.is_superuser or is_verification_officer(request.user) or (cert.holder and cert.holder.id == request.user.id)):
            raise PermissionDenied("You do not have authorization to download this certificate.")
        
        if cert.status != 'active':
            messages.warning(request, f"Certificate {cert.certificate_id} is in status '{cert.get_status_display()}'. PDFs can only be downloaded once activated.")
            return redirect('verification:my_certificate', certificate_id=cert.certificate_id)

        # Resolve base URL for QR code (prefer local network Wi-Fi IP in development so mobile scans work)
        host = request.get_host().split(':')[0]
        if host in ('localhost', '127.0.0.1', '::1'):
            try:
                hostname = socket.gethostname()
                local_ips = socket.gethostbyname_ex(hostname)[2]
                routable_ips = [ip for ip in local_ips if not ip.startswith('127.')]
                if routable_ips:
                    port = request.get_port()
                    base_url = f"{request.scheme}://{routable_ips[0]}:{port}"
                else:
                    base_url = request.build_absolute_uri('/')[:-1]
            except Exception:
                base_url = request.build_absolute_uri('/')[:-1]
        else:
            base_url = request.build_absolute_uri('/')[:-1]

        pdf_bytes = generate_certificate_pdf_bytes(cert, base_url=base_url)
        response = HttpResponse(pdf_bytes, content_type='application/pdf')
        response['Content-Disposition'] = f'attachment; filename="VerifyNG_Certificate_{cert.certificate_id}.pdf"'
        return response



class CertificatePublicVerifyView(View):
    """
    Public digital verification badge for physical & PDF certificate QR scans.
    No login required. Allows employers, landlords, and embassies to instantly
    confirm authenticity while keeping candidate private PII masked and safe.
    """
    template_name = 'verification/certificate_public_verify.html'
    def get(self, request, certificate_id):
        from core.rate_limiting import check_rate_limit
        import re

        # Rate limit to protect QR verification endpoint against automated scraping
        is_limited, retry_after = check_rate_limit(request, namespace="qr_verify", limit=60, window=60)
        if is_limited:
            response = HttpResponse(
                "Rate limit exceeded. Please wait a moment before scanning again.",
                status=429,
                content_type="text/plain; charset=utf-8"
            )
            response['Retry-After'] = str(retry_after)
            return response

        # Strict format validation: only permit standard certificate reference characters
        cert_id_clean = (certificate_id or '').strip().upper()
        if not re.match(r'^[A-Z0-9-]{5,40}$', cert_id_clean):
            return render(request, self.template_name, {
                'certificate_id': certificate_id,
                'lookup_state': 'NOT_FOUND',
                'candidate_name': '—',
                'nin_masked': '—',
            })

        cert = VerificationCertificate.objects.filter(certificate_id=cert_id_clean).select_related('holder', 'subject').first()
        try:
            AuditLog.objects.create(
                report=None,
                action="CERTIFICATE_PUBLIC_QR_SCANNED",
                performed_by=request.user if request.user.is_authenticated else None,
                ip_address=get_client_ip(request),
                details={
                    "certificate_id": certificate_id,
                    "found": cert is not None,
                    "status": cert.status if cert else "NOT_FOUND",
                    "user_agent": request.META.get('HTTP_USER_AGENT', '')[:200],
                }
            )
        except Exception:
            pass

        if not cert:
            lookup_state = 'NOT_FOUND'
        elif cert.status == 'revoked':
            lookup_state = 'REVOKED'
        elif cert.status == 'suspended':
            lookup_state = 'SUSPENDED'
        elif not cert.is_valid:
            lookup_state = 'EXPIRED'
        elif not cert.is_live_searchable:
            lookup_state = 'GRACE_EXPIRED_MONITORING_REQUIRED'
        else:
            lookup_state = 'ACTIVE_VALID'

        candidate_name = '—'
        nin_masked = 'Verified Record'
        det = {}
        if cert:
            app_log = None
            for l in AuditLog.objects.filter(action="TRUSTPASS_APPLICATION_SUBMITTED").order_by('-timestamp')[:50]:
                d = l.details if isinstance(l.details, dict) else {}
                if d.get('certificate_id') == cert.certificate_id:
                    app_log = l
                    break
            det = app_log.details if (app_log and isinstance(app_log.details, dict)) else {}

            candidate_name = (cert.subject.name if cert.subject else None) or det.get('full_name')
            if not candidate_name and cert.holder:
                candidate_name = cert.holder.get_full_name() or cert.holder.username
            nin_raw = det.get('nin', '')
            nin_masked = det.get('nin_masked')
            if not nin_masked and nin_raw and len(nin_raw) >= 6:
                nin_masked = nin_raw[:3] + '****' + nin_raw[-2:]
            elif not nin_masked:
                nin_masked = 'Verified Record'

        return render(request, self.template_name, {
            'certificate': cert,
            'certificate_id': certificate_id,
            'candidate_name': candidate_name,
            'check_level': cert.get_check_level_display() if (cert and hasattr(cert, 'get_check_level_display')) else (cert.check_level if cert else 'Standard'),
            'status': cert.status if cert else 'not_found',
            'lookup_state': lookup_state,
            'is_valid': (lookup_state == 'ACTIVE_VALID'),
            'dob': det.get('date_of_birth', '—'),
            'nin_masked': nin_masked,
            'employer_name': det.get('employer_name', '—'),
            'job_role': det.get('job_role', '—'),
            'issued_date': (cert.issued_at or cert.created_at) if cert else None,
            'expires_at': cert.expires_at if cert else None,
        })


class MyCertificatesListView(LoginRequiredMixin, ListView):
    """
    Lists all certificates belonging to the logged-in user.
    Officers and superusers see all certificates.
    """
    model = VerificationCertificate
    template_name = 'verification/my_certificates_list.html'
    context_object_name = 'certificates'
    paginate_by = 20

    def get_queryset(self):
        user = self.request.user
        if user.is_superuser or is_verification_officer(user):
            return (
                VerificationCertificate.objects
                .select_related('subject', 'holder')
                .order_by('-created_at')
            )
        return (
            VerificationCertificate.objects
            .filter(holder=user)
            .select_related('subject', 'holder')
            .order_by('-created_at')
        )
    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['is_officer'] = (
            is_verification_officer(self.request.user)
            or self.request.user.is_superuser
        )
        return ctx


class CertificateQueryLandingView(View):
    """
    Public GET: Landing page for third-party employers/landlords to query a certificate.
    POST: Initiates Paystack payment for the query.

    No login required for GET (public-facing).
    Login required for POST (payment must be tied to an authenticated user account).
    """
    template_name = 'verification/certificate_query_landing.html'

    def get(self, request):
        cert_id = request.GET.get('cert_id', '')
        certificate = None
        if cert_id:
            certificate = VerificationCertificate.objects.filter(
                certificate_id=cert_id,
                is_active=True
            ).first()
        return render(request, self.template_name, {
            'certificate': certificate,
            'cert_id': cert_id,
        })

    def post(self, request):
        if not request.user.is_authenticated:
            messages.info(request, "Please sign in to proceed with certificate verification.")
            return redirect(f"{reverse('users:login')}?next={request.path}")

        cert_id = request.POST.get('cert_id', '').strip()
        purpose = request.POST.get('purpose', '').strip()

        if not cert_id:
            messages.error(request, "Certificate ID is required.")
            return redirect('verification:certificate_query_landing')

        certificate = get_object_or_404(
            VerificationCertificate.objects.select_related('subject', 'holder'),
            certificate_id=cert_id,
            is_active=True
        )

        ip_addr = get_client_ip(request)

        try:
            tx = initialize_certificate_query_transaction(request.user, certificate)
        except Exception as e:
            logger.error("Failed to initialize certificate query transaction: %s", str(e))
            messages.error(request, "Unable to initiate payment. Please try again.")
            return redirect('verification:certificate_query_landing')

        tx_reference = tx.get('reference', '') if isinstance(tx, dict) else getattr(tx, 'reference', '')

        request.session['pending_cert_query'] = {
            'certificate_id': cert_id,
            'transaction_reference': tx_reference,
            'purpose': purpose,
            'ip_address': ip_addr,
        }

        # Redirect to Paystack — handled by payments app
        return redirect(f"/payments/callback/?reference={tx_reference}")


class CertificateQueryResultView(LoginRequiredMixin, View):
    """
    Post-payment callback view.
    Verifies payment status, logs the query, and displays certificate result.

    Called after Paystack redirects back to VerifyNG with the transaction reference.
    """
    template_name = 'verification/certificate_query_result.html'

    def get(self, request):

        pending = request.session.pop('pending_cert_query', None)
        if not pending:
            messages.error(request, "No pending certificate query found. Please start again.")
            return redirect('verification:certificate_query_landing')

        cert_id = pending.get('certificate_id')
        tx_ref = pending.get('transaction_reference')
        purpose = pending.get('purpose', '')
        ip_addr = pending.get('ip_address') or get_client_ip(request)

        # Verify transaction succeeded
        try:
            tx = Transaction.objects.get(reference=tx_ref, user=request.user)
        except Transaction.DoesNotExist:
            messages.error(request, "Payment record not found. Please contact support.")
            return redirect('verification:certificate_query_landing')

        if tx.status != 'success':
            messages.warning(
                request,
                f"Payment not confirmed (status: {tx.status}). "
                "Please wait or contact support if you believe this is an error."
            )
            return redirect('verification:certificate_query_landing')

        certificate = get_object_or_404(
            VerificationCertificate.objects.select_related('subject', 'holder'),
            certificate_id=cert_id,
            is_active=True
        )

        # Append-only audit log — only after payment confirmed
        log_certificate_query(
            certificate=certificate,
            queried_by=request.user,
            ip_address=ip_addr,
            payment=tx,
            purpose=purpose,
        )

        AuditLog.objects.create(
            report=None,
            action="CERTIFICATE_QUERY_COMPLETED",
            performed_by=request.user,
            ip_address=ip_addr,
            details={
                "certificate_id": cert_id,
                "transaction_reference": tx_ref,
                "purpose": purpose,
                "is_valid": certificate.is_valid,
            }
        )

        # Query verified (published) misconduct determinations for this certificate's subject
        adjudicated_reports = FraudReport.objects.filter(
            target_subject=certificate.subject,
            state='published'
        ).order_by('-created_at')
        return render(request, self.template_name, {
            'certificate': certificate,
            'is_valid': certificate.is_valid,
            'query_purpose': purpose,
            'adjudicated_reports': adjudicated_reports,
            'is_clean_record': not adjudicated_reports.exists(),
        })


class CertificateQueryLogView(LoginRequiredMixin, ListView):
    """
    Shows the query log for a certificate — visible to:
    - The original certificate holder (requester)
    - Verification officers
    - Superusers
    """
    model = CertificateQueryLog
    template_name = 'verification/query_log.html'
    context_object_name = 'query_logs'
    paginate_by = 25

    def get_queryset(self):
        cert_id = self.kwargs.get('certificate_id')
        self._certificate = get_object_or_404(
            VerificationCertificate.objects.select_related('subject', 'holder'),
            certificate_id=cert_id
        )
        if (
            not self.request.user.is_superuser
            and not is_verification_officer(self.request.user)
            and (self._certificate.holder is None or self._certificate.holder.id != self.request.user.id)
        ):
            raise PermissionDenied("You do not have authorization to view this query log.")

        return (
            CertificateQueryLog.objects
            .filter(certificate=self._certificate)
            .select_related('queried_by')
            .order_by('-queried_at')
        )

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['certificate'] = self._certificate
        return ctx
    



class CertificateActivateView(LoginRequiredMixin, View):
    """
    POST-only. Officer/superuser activates a pending certificate.

    Transitions: pending → active
    Sets issued_at and expires_at on the model.
    Access: Verification officers and superusers only.
    """

    def post(self, request, certificate_id):
        if not (is_verification_officer(request.user) or request.user.is_superuser):
            raise PermissionDenied("Verification Officer authorization required.")

        certificate = get_object_or_404(
            VerificationCertificate.objects.select_related('holder', 'subject'),
            certificate_id=certificate_id,
        )

        try:
            certificate.activate()
            AuditLog.objects.create(
                report=None,
                action="CERTIFICATE_ACTIVATED",
                performed_by=request.user,
                ip_address=get_client_ip(request),
                details={
                    "certificate_id": certificate_id,
                    "holder": certificate.holder.username if certificate.holder else None,
                    "check_level": certificate.check_level,
                    "issued_at": certificate.issued_at.isoformat() if certificate.issued_at else None,
                    "expires_at": certificate.expires_at.isoformat() if certificate.expires_at else None,
                }
            )
            # Generate PDF asynchronously — runs in background via Celery
            
            generate_certificate_pdf.delay(certificate_id)

            messages.success(
                request,
                f"Certificate [{certificate_id}] activated successfully. "
                f"Valid until {certificate.expires_at.strftime('%d %b %Y') if certificate.expires_at else 'no expiry'}."
            )
        except ValueError as e:
            messages.error(request, str(e))

        return redirect('verification:my_certificate', certificate_id=certificate_id)


class CertificateRevokeView(LoginRequiredMixin, View):
    """
    POST-only. Officer/superuser revokes an active or suspended certificate.

    Transitions: active|suspended → revoked
    Requires 'reason' in POST body.
    Access: Verification officers and superusers only.
    """

    def post(self, request, certificate_id):
        if not (is_verification_officer(request.user) or request.user.is_superuser):
            raise PermissionDenied("Verification Officer authorization required.")

        certificate = get_object_or_404(
            VerificationCertificate.objects.select_related('holder', 'subject'),
            certificate_id=certificate_id,
        )

        reason = request.POST.get('reason', '').strip()
        if not reason:
            messages.error(request, "A revocation reason is required.")
            return redirect('verification:my_certificate', certificate_id=certificate_id)

        try:
            certificate.revoke(reason=reason)
            AuditLog.objects.create(
                report=None,
                action="CERTIFICATE_REVOKED",
                performed_by=request.user,
                ip_address=get_client_ip(request),
                details={
                    "certificate_id": certificate_id,
                    "holder": certificate.holder.username if certificate.holder else None,
                    "reason": reason,
                }
            )
            messages.success(
                request,
                f"Certificate [{certificate_id}] has been revoked."
            )
        except ValueError as e:
            messages.error(request, str(e))

        return redirect('verification:my_certificate', certificate_id=certificate_id)




class VerificationDocumentView(LoginRequiredMixin, View):
    """
    Secure document stream proxy for viewing supporting documents uploaded with a verification request.
    Only authorized parties (applicant requester, assigned officer, superuser) can view the file.
    Streams inline by default (for in-browser PDF / image preview) or downloads if ?download=1.
    """
    def get(self, request, reference_number, doc_id=None):
        verif_request = get_object_or_404(
            VerificationRequest.objects.select_related('requester').prefetch_related('documents'),
            reference_number=reference_number
        )
        if not can_view_verification(request.user, verif_request):
            raise PermissionDenied("You do not have authorization to view this document.")

        doc_field = None
        doc_name = ''

        if doc_id:
            doc = get_object_or_404(verif_request.documents, pk=doc_id)
            doc_field = doc.file
            doc_name = doc.document_name or (doc.file.name.split('/')[-1] if doc.file else 'document')
        else:
            first_doc = verif_request.documents.first()
            if first_doc and first_doc.file:
                doc_field = first_doc.file
                doc_name = first_doc.document_name or (first_doc.file.name.split('/')[-1] if first_doc.file else 'document')
            elif verif_request.document:
                doc_field = verif_request.document
                doc_name = verif_request.document.name.split('/')[-1] if verif_request.document.name else 'document'

        if not doc_field or not getattr(doc_field, 'name', None):
            msg = "No supporting document file has been uploaded for this verification request."
            if request.user.is_superuser or is_verification_officer(request.user):
                messages.warning(request, msg)
                return redirect('admin_portal:verification_detail', pk=verif_request.pk)
            else:
                messages.warning(request, msg)
                return redirect('verification:detail', reference_number=verif_request.reference_number)

        try:
            opened_file = doc_field.open('rb')
        except Exception:
            msg = f"The requested document ({doc_name}) was not found in storage or could not be opened."
            if request.user.is_superuser or is_verification_officer(request.user):
                messages.warning(request, msg)
                return redirect('admin_portal:verification_detail', pk=verif_request.pk)
            else:
                messages.warning(request, msg)
                return redirect('verification:detail', reference_number=verif_request.reference_number)

        ext = doc_name.split('.')[-1].lower() if '.' in doc_name else 'pdf'
        content_type, _ = mimetypes.guess_type(doc_name)
        if not content_type:
            content_type = 'application/pdf' if ext == 'pdf' else 'image/jpeg'

        as_download = request.GET.get('download') == '1'
        disposition = 'attachment' if as_download else 'inline'
        safe_name = f"{verif_request.reference_number}_{slugify(doc_name.rsplit('.', 1)[0]) or 'document'}.{ext}"

        response = HttpResponse(opened_file.read(), content_type=content_type)
        response['Content-Disposition'] = f'{disposition}; filename="{safe_name}"'
        response['X-Frame-Options'] = 'SAMEORIGIN'
        opened_file.close()
        return response

# ==============================================================================
# DBS-Style Continuous Update Service Views
# ==============================================================================

def _get_update_service_cert(request):
    """
    Retrieves the certificate active in the current Update Service guest session,
    or from the authenticated user's portfolio if logged in.
    Strictly requires status == 'active' (approved by officer/admin).
    """
    cert_id = request.session.get('update_service_cert_id')
    if cert_id:
        cert = VerificationCertificate.objects.filter(certificate_id=cert_id, status='active', is_active=True).first()
        if cert:
            return cert
    if request.user.is_authenticated:
        req_cert_id = request.GET.get('cert')
        if req_cert_id:
            cert = VerificationCertificate.objects.filter(certificate_id=req_cert_id, holder=request.user, status='active', is_active=True).first()
            if cert:
                return cert
        return VerificationCertificate.objects.filter(holder=request.user, status='active', is_active=True).order_by('-created_at').first()
    return None


class UpdateServiceLoginView(View):
    """
    Public entry point for certificate holders to log into their Update Service portal.
    Authenticates by Certificate ID + Surname + Date of Birth.
    Strictly isolated: does NOT log user into main Django account.
    """
    template_name = 'verification/update_service_login.html'

    def dispatch(self, request, *args, **kwargs):
        if request.user.is_authenticated and not (request.user.is_staff or request.user.is_superuser):
            if is_employer(request.user):
                messages.info(request, "Employers verify candidate certificates via the Verify Certificate tool. The Continuous Update Service is managed directly by the individual certificate holder.")
                return redirect('employer:certificate_verify')
        return super().dispatch(request, *args, **kwargs)

    def get(self, request):
        from verification.forms import UpdateServiceLoginForm
        initial = {}
        if 'cert' in request.GET:
            initial['certificate_id'] = request.GET.get('cert')
        form = UpdateServiceLoginForm(initial=initial)
        return render(request, self.template_name, {'form': form})

    def post(self, request):
        import re
        from verification.forms import UpdateServiceLoginForm
        form = UpdateServiceLoginForm(request.POST)
        if not form.is_valid():
            return render(request, self.template_name, {'form': form})

        cert_id = form.cleaned_data['certificate_id'].strip().upper()
        surname_input = form.cleaned_data['surname'].strip().lower()
        dob_input = form.cleaned_data['date_of_birth']
        dob_str = dob_input.strftime('%Y-%m-%d')

        cert = VerificationCertificate.objects.filter(certificate_id__iexact=cert_id, is_active=True).first()
        if not cert:
            form.add_error(None, "No clearance certificate found with this Reference ID. Please verify the characters.")
            return render(request, self.template_name, {'form': form})

        if cert.status != 'active':
            form.add_error(None, f"Certificate {cert.certificate_id} has not been approved by an administrator yet ({cert.get_status_display()}). Only approved certificates can access the Continuous Update Service.")
            return render(request, self.template_name, {'form': form})

        # Retrieve application metadata from AuditLog or SubjectEntity
        app_log = AuditLog.objects.filter(
            action__in=["UPDATE_SERVICE_ENROLLED", "TRUSTPASS_APPLICATION_SUBMITTED"]
        ).order_by('-timestamp')
        det = {}
        for l in app_log[:50]:
            d = l.details if isinstance(l.details, dict) else {}
            if d.get('certificate_id') == cert.certificate_id:
                for k, v in d.items():
                    if k not in det and v:
                        det[k] = v

        cand_name = (cert.subject.name if cert.subject else None) or det.get('full_name') or ''
        if not cand_name and cert.holder:
            cand_name = cert.holder.get_full_name() or cert.holder.username

        # Tokenize and check surname
        cand_tokens = [t.lower() for t in re.split(r'[\s,\.-]+', cand_name) if t]
        holder_last = (cert.holder.last_name or '').lower() if cert.holder else ''
        surname_matches = (
            surname_input in cand_tokens
            or surname_input == holder_last
            or (len(surname_input) >= 3 and any(surname_input in tok or tok in surname_input for tok in cand_tokens))
        )

        reg_dob = str(det.get('date_of_birth', '')).strip()
        if not reg_dob and getattr(cert.holder, 'date_of_birth', None):
            reg_dob = cert.holder.date_of_birth.strftime('%Y-%m-%d')

        dob_matches = True
        if reg_dob:
            dob_matches = (dob_str == reg_dob)

        if not surname_matches or not dob_matches:
            form.add_error(None, "The surname or date of birth entered does not match our records for this certificate.")
            return render(request, self.template_name, {'form': form})

        # Success: Store certificate ID in session (Update-Service scoped ONLY)
        request.session['update_service_cert_id'] = cert.certificate_id
        if cert.is_monitoring_valid:
            messages.success(request, f"Welcome to your Continuous Update Service portal, {surname_input.title()}.")
            return redirect('verification:update_service_portal')
        elif cert.in_grace_period:
            messages.info(
                request,
                f"Certificate {cert.certificate_id} is within its 30-day window ({cert.grace_days_remaining} days left). "
                "Join the Continuous Update Service to activate your portal and keep your clearance searchable online."
            )
            return redirect(f"{reverse('verification:update_service_join')}?cert={cert.certificate_id}")
        else:
            request.session.pop('update_service_cert_id', None)
            form.add_error(
                None,
                "This certificate was not registered in the Continuous Update Service within 30 days of issue. "
                "The enrollment window has expired. A new clearance certificate is required."
            )
            return render(request, self.template_name, {'form': form})


class UpdateServiceJoinView(View):
    """
    Candidate enrollment wizard to join the Continuous Update Service.
    Enforces the 30-day initial window rule:
      - Validates certificate reference
      - When user has multiple eligible certificates, prompts selection
      - Verifies days_since_issued <= 30
      - Allows candidate to review and complete contact details (phone, residential address, email)
      - Summary review (₦3,000/yr annual fee)
      - Redirects to Paystack checkout to activate continuous monitoring
    """
    template_name = 'verification/update_service_join.html'

    def dispatch(self, request, *args, **kwargs):
        if request.user.is_authenticated and not (request.user.is_staff or request.user.is_superuser):
            if is_employer(request.user):
                messages.info(request, "Employers verify candidate certificates via the Verify Certificate tool. The Continuous Update Service is managed directly by the individual certificate holder.")
                return redirect('employer:certificate_verify')
        return super().dispatch(request, *args, **kwargs)

    def get(self, request):
        from verification.forms import UpdateServiceJoinForm
        site_settings = SiteSettings.get()
        annual_fee = site_settings.price_monitoring_annual

        req_cert_id = request.GET.get('cert')
        choose_mode = request.GET.get('choose') == '1'

        user_certs = []
        eligible_certs = []
        if request.user.is_authenticated:
            # Query active (officer-approved) certificates for the user
            user_certs = list(
                VerificationCertificate.objects.filter(
                    holder=request.user, 
                    status='active', 
                    is_active=True
                ).order_by('-created_at')
            )
            eligible_certs = [c for c in user_certs if c.in_grace_period and not c.is_monitoring_valid]

            # If user explicitly chooses manual entry / wants to enter another certificate
            if request.GET.get('manual') == '1':
                return render(request, self.template_name, {
                    'cert': None,
                    'manual_lookup': True,
                    'user_certs': user_certs,
                    'annual_fee': annual_fee,
                })

            # If user has multiple eligible certificates and hasn't picked one (or wants to choose):
            if (len(eligible_certs) > 1 and not req_cert_id) or (choose_mode and len(eligible_certs) > 1):
                return render(request, self.template_name, {
                    'choose_certificate': True,
                    'eligible_certs': eligible_certs,
                    'annual_fee': annual_fee,
                })

            # If user has no active certificates and hasn't provided ?cert=, show the certificate lookup form!
            if not user_certs and not req_cert_id:
                has_pending = VerificationCertificate.objects.filter(
                    holder=request.user, 
                    is_active=True
                ).exclude(status='active').exists()
                return render(request, self.template_name, {
                    'cert': None,
                    'manual_lookup': True,
                    'has_pending_notice': has_pending,
                    'annual_fee': annual_fee,
                })

            # If user has personal certificates but none are eligible (e.g. all monitoring_valid or all expired):
            if not eligible_certs and not req_cert_id:
                if all(c.is_monitoring_valid for c in user_certs):
                    messages.info(request, "All your personal certificates are already enrolled in the Continuous Update Service. You can enter an employer-sponsored certificate reference below to enroll another credential.")
                    return render(request, self.template_name, {
                        'cert': None,
                        'manual_lookup': True,
                        'annual_fee': annual_fee,
                    })
                first_cert = user_certs[0]
                return render(request, self.template_name, {
                    'cert': first_cert,
                    'window_expired': True,
                    'days_since_issued': first_cert.days_since_issued,
                    'allow_manual_entry': True,
                    'annual_fee': annual_fee,
                })

        # Resolve single certificate
        cert = None
        if req_cert_id:
            raw_cert = VerificationCertificate.objects.filter(certificate_id__iexact=req_cert_id.strip(), is_active=True).first()
            if not raw_cert:
                messages.error(request, f"No certificate found matching reference '{req_cert_id.strip()}'. Please verify the certificate reference number and try again.")
                return render(request, self.template_name, {'cert': None, 'annual_fee': annual_fee})
            if raw_cert.status != 'active':
                messages.warning(
                    request,
                    f"Certificate {raw_cert.certificate_id} has not been approved yet ({raw_cert.get_status_display()}). "
                    "Only approved/active certificates can be enrolled in the Continuous Update Service."
                )
                return redirect('verification:my_certificates' if request.user.is_authenticated else 'verification:update_service_login')
            cert = raw_cert
        elif request.user.is_authenticated:
            if eligible_certs:
                cert = eligible_certs[0]
            elif user_certs:
                cert = user_certs[0]
        else:
            session_cert_id = request.session.get('update_service_cert_id')
            if session_cert_id:
                cert = VerificationCertificate.objects.filter(certificate_id=session_cert_id, status='active', is_active=True).first()

        if not cert:
            return render(request, self.template_name, {'cert': None, 'annual_fee': annual_fee})

        # If already subscribed, redirect to portal
        if cert.is_monitoring_valid:
            messages.info(request, f"Certificate {cert.certificate_id} is already enrolled in the Continuous Update Service.")
            request.session['update_service_cert_id'] = cert.certificate_id
            return redirect('verification:update_service_portal')

        # Check 30-day eligibility window
        if not cert.in_grace_period:
            return render(request, self.template_name, {
                'cert': cert,
                'window_expired': True,
                'days_since_issued': cert.days_since_issued,
            })

        # Eligible: Retrieve name, email, phone, residential address
        app_log = AuditLog.objects.filter(
            action__in=["UPDATE_SERVICE_ENROLLED", "TRUSTPASS_APPLICATION_SUBMITTED"]
        ).order_by('-timestamp')
        det = {}
        for l in app_log[:50]:
            d = l.details if isinstance(l.details, dict) else {}
            if d.get('certificate_id') == cert.certificate_id:
                for k, v in d.items():
                    if k not in det and v:
                        det[k] = v

        cand_name = (cert.subject.name if cert.subject else None) or det.get('full_name') or ''
        if not cand_name and cert.holder:
            cand_name = cert.holder.get_full_name() or cert.holder.username

        initial_email = (cert.holder.email if cert.holder else '') or det.get('email', '')
        initial_phone = (getattr(cert.holder, 'phone_number', '') if cert.holder else '') or det.get('phone_number', '')
        initial_address = (getattr(cert.holder, 'address', '') if cert.holder else '') or det.get('residential_address') or det.get('address') or ''

        form = UpdateServiceJoinForm(initial={
            'certificate_id': cert.certificate_id,
            'full_name': cand_name,
            'email': initial_email,
            'phone_number': initial_phone,
            'residential_address': initial_address,
        })

        has_multiple_eligible = (len(eligible_certs) > 1) if request.user.is_authenticated else False

        user_balance = 0
        topup_needed = annual_fee
        if request.user.is_authenticated:
            from payments.services import get_user_prepaid_balance, get_topup_difference
            user_balance = get_user_prepaid_balance(request.user)
            topup_needed = get_topup_difference(user_balance, annual_fee)

        return render(request, self.template_name, {
            'cert': cert,
            'form': form,
            'cand_name': cand_name,
            'annual_fee': annual_fee,
            'user_balance': user_balance,
            'topup_needed': topup_needed,
            'days_remaining': cert.grace_days_remaining,
            'window_expired': False,
            'has_multiple_eligible': has_multiple_eligible,
        })

    def post(self, request):
        from verification.forms import UpdateServiceJoinForm
        form = UpdateServiceJoinForm(request.POST)
        if not form.is_valid():
            cert_id = request.POST.get('certificate_id')
            cert = VerificationCertificate.objects.filter(certificate_id__iexact=cert_id, is_active=True).first() if cert_id else None
            site_settings = SiteSettings.get()
            annual_fee = site_settings.price_monitoring_annual
            user_balance = 0
            topup_needed = annual_fee
            if request.user.is_authenticated:
                from payments.services import get_user_prepaid_balance, get_topup_difference
                user_balance = get_user_prepaid_balance(request.user)
                topup_needed = get_topup_difference(user_balance, annual_fee)
            return render(request, self.template_name, {
                'cert': cert,
                'form': form,
                'annual_fee': annual_fee,
                'user_balance': user_balance,
                'topup_needed': topup_needed,
                'days_remaining': cert.grace_days_remaining if cert else 0,
                'window_expired': False,
            })

        cert_id = form.cleaned_data['certificate_id'].strip().upper()
        cert = VerificationCertificate.objects.filter(certificate_id__iexact=cert_id, is_active=True).first()
        if not cert:
            messages.error(request, "No active clearance certificate found matching this Reference ID.")
            return redirect('verification:update_service_join')

        if cert.status != 'active':
            messages.error(
                request,
                f"Certificate {cert.certificate_id} has not been approved by an administrator yet ({cert.get_status_display()}). "
                "Only officially approved certificates can be added to the Continuous Update Service."
            )
            return redirect('verification:my_certificates' if request.user.is_authenticated else 'verification:update_service_join')

        if not cert.in_grace_period:
            messages.error(request, "This certificate is beyond the 30-day enrollment window and cannot be added to the Update Service.")
            return redirect('verification:update_service_join')

        if request.user.is_authenticated and not cert.holder:
            cert.holder = request.user
            cert.save(update_fields=['holder'])
        elif cert.holder:
            if form.cleaned_data.get('phone_number'):
                cert.holder.phone_number = form.cleaned_data['phone_number']
            if form.cleaned_data.get('residential_address'):
                cert.holder.address = form.cleaned_data['residential_address']
            cert.holder.save()

        request.session['update_service_cert_id'] = cert.certificate_id

        site_settings = SiteSettings.get()
        amount_naira = site_settings.price_monitoring_annual

        user_balance = 0
        if request.user.is_authenticated:
            from payments.services import get_user_prepaid_balance, deduct_user_prepaid_balance, get_topup_difference
            user_balance = get_user_prepaid_balance(request.user)

        # 1. Full coverage from user available account balance
        if request.user.is_authenticated and user_balance >= amount_naira:
            ok, rem_bal = deduct_user_prepaid_balance(request.user, amount_naira, f"Update Service: {cert.certificate_id}")
            if ok:
                from datetime import timedelta
                from django.utils import timezone
                from core.audit_utils import log_admin_action

                now = timezone.now()
                cert.is_monitoring_active = True
                cert.monitoring_activated_at = now
                cert.monitoring_expires_at = now + timedelta(days=365)
                update_fields = ['is_monitoring_active', 'monitoring_activated_at', 'monitoring_expires_at', 'updated_at']
                if cert.holder != request.user:
                    cert.holder = request.user
                    update_fields.append('holder')
                cert.save(update_fields=update_fields)

                log_admin_action(
                    action='UPDATE_SERVICE_ENROLLED',
                    action_type='VERIFICATION',
                    performed_by=request.user,
                    target_user=request.user,
                    request=request,
                    details={
                        'certificate_id': cert.certificate_id,
                        'payment_method': 'account_balance',
                        'amount_naira': float(amount_naira),
                        'remaining_balance_naira': rem_bal,
                        'expires_at': cert.monitoring_expires_at.isoformat(),
                        'phone_number': form.cleaned_data.get('phone_number', ''),
                        'residential_address': form.cleaned_data.get('residential_address', ''),
                        'email': form.cleaned_data.get('email', ''),
                    }
                )
                messages.success(
                    request,
                    f"?{amount_naira:,.0f} deducted from your account balance successfully (Remaining balance: ?{rem_bal:,.0f}). "
                    "Your certificate is now registered on the Continuous Update Service for 1 year."
                )
                return redirect('verification:update_service_portal')

        # 2. Partial coverage from balance + top-up difference via Paystack
        user = request.user if request.user.is_authenticated else cert.holder
        checkout_amount = amount_naira
        if request.user.is_authenticated and 0 < user_balance < amount_naira:
            topup_needed = get_topup_difference(user_balance, amount_naira)
            deduct_user_prepaid_balance(request.user, user_balance, f"Partial top-up for Update Service {cert.certificate_id}")
            checkout_amount = topup_needed

        # 3. Checkout via Paystack
        try:
            checkout_res = initialize_service_checkout(
                user=user,
                service='monitoring',
                tier='annual',
                amount_naira=checkout_amount,
                metadata={
                    'service': 'monitoring',
                    'certificate_id': cert.certificate_id,
                    'phone': form.cleaned_data['phone_number'],
                    'address': form.cleaned_data['residential_address'],
                    'email': form.cleaned_data['email'],
                }
            )
            return redirect(checkout_res['authorization_url'])
        except Exception as e:
            messages.error(request, f"Unable to initialize payment gateway: {e}")
            return redirect(f"{reverse('verification:update_service_join')}?cert={cert.certificate_id}")


class UpdateServicePortalView(View):
    """
    Dedicated Update Service applicant dashboard matching the UK DBS standard.
    Displays:
      - Candidate Contact Details (left)
      - Applications and Certificates Table with Update Status (right)
      - Link: 'View who has carried out a Status check on your Certificates'
      - Active Subscription & Expiry Card
    """
    template_name = 'verification/update_service_portal.html'

    def dispatch(self, request, *args, **kwargs):
        if request.user.is_authenticated and not (request.user.is_staff or request.user.is_superuser):
            if is_employer(request.user):
                messages.info(request, "Employers verify candidate certificates via the Verify Certificate tool. The Continuous Update Service is managed directly by the individual certificate holder.")
                return redirect('employer:certificate_verify')
        return super().dispatch(request, *args, **kwargs)

    def get(self, request):
        cert = _get_update_service_cert(request)
        if not cert:
            if request.user.is_authenticated:
                messages.info(request, "You do not have an active clearance certificate yet. Please apply for a TrustPass certificate first to join the Continuous Update Service.")
                return redirect('verification:certificate_apply')
            messages.info(request, "Please enter your Certificate ID, Surname, and Date of Birth to access your Update Service.")
            return redirect('verification:update_service_login')

        if not cert.is_monitoring_valid:
            if cert.in_grace_period:
                messages.warning(
                    request,
                    f"Certificate {cert.certificate_id} has not been added to the Continuous Update Service yet. "
                    f"Please complete registration below within your 30-day window ({cert.grace_days_remaining} days left) to activate your portal."
                )
                return redirect(f"{reverse('verification:update_service_join')}?cert={cert.certificate_id}")
            else:
                messages.error(
                    request,
                    f"Certificate {cert.certificate_id} was not enrolled in the Update Service within 30 days and has expired from online search. A new certificate is required."
                )
                return redirect('verification:my_certificates' if request.user.is_authenticated else 'verification:update_service_login')

        # Retrieve application metadata
        app_log = AuditLog.objects.filter(
            action__in=["UPDATE_SERVICE_ENROLLED", "TRUSTPASS_APPLICATION_SUBMITTED"]
        ).order_by('-timestamp')
        det = {}
        for l in app_log[:50]:
            d = l.details if isinstance(l.details, dict) else {}
            if d.get('certificate_id') == cert.certificate_id:
                for k, v in d.items():
                    if k not in det and v:
                        det[k] = v

        cand_name = (cert.subject.name if cert.subject else None) or det.get('full_name') or ''
        if not cand_name and cert.holder:
            cand_name = cert.holder.get_full_name() or cert.holder.username

        # Contact info
        contact_email = (cert.holder.email if cert.holder else '') or det.get('email', '')
        contact_phone = (getattr(cert.holder, 'phone_number', '') if cert.holder else '') or det.get('phone_number', '')
        contact_address = (getattr(cert.holder, 'address', '') if cert.holder else '') or det.get('residential_address') or det.get('address') or 'Nigeria'

        # Check for any adverse reports
        has_adverse = False
        if cert.subject:
            has_adverse = FraudReport.objects.filter(target_subject=cert.subject, state='published').exists()

        try:
            from employer.models import StaffMisconductReport
            nin_val = getattr(cert.holder, 'id_number', None) if cert.holder else None
            if nin_val and not has_adverse:
                has_adverse = StaffMisconductReport.objects.filter(nin=nin_val, status='adjudicated_verified').exists()
        except Exception:
            pass

        if has_adverse:
            update_status_display = "New adverse record reported"
            update_status_badge = "danger"
        else:
            update_status_display = "Blank, no new information"
            update_status_badge = "success"

        site_settings = SiteSettings.get()
        annual_fee = site_settings.price_monitoring_annual

        context = {
            'cert': cert,
            'candidate_name': cand_name,
            'contact_email': contact_email,
            'contact_phone': contact_phone,
            'contact_address': contact_address,
            'application_ref': getattr(cert, 'application_reference', '') or f"APP-{cert.certificate_id.split('-')[-1]}",
            'update_status_display': update_status_display,
            'update_status_badge': update_status_badge,
            'is_monitoring_valid': cert.is_monitoring_valid,
            'in_grace_period': cert.in_grace_period,
            'grace_days_remaining': cert.grace_days_remaining,
            'monitoring_expires_at': cert.monitoring_expires_at,
            'annual_fee': annual_fee,
            'query_logs_count': cert.query_logs.count(),
        }
        return render(request, self.template_name, context)


class UpdateServiceAuditLogView(View):
    """
    'View who has carried out a Status check on your Certificates'
    Displays all queries performed on this certificate by employers and organisations.
    """
    template_name = 'verification/update_service_audit_log.html'

    def dispatch(self, request, *args, **kwargs):
        if request.user.is_authenticated and not (request.user.is_staff or request.user.is_superuser):
            if is_employer(request.user):
                messages.info(request, "Employers verify candidate certificates via the Verify Certificate tool. The Continuous Update Service is managed directly by the individual certificate holder.")
                return redirect('employer:certificate_verify')
        return super().dispatch(request, *args, **kwargs)

    def get(self, request):
        cert = _get_update_service_cert(request)
        if not cert:
            messages.info(request, "Please enter your Certificate ID, Surname, and Date of Birth to access the query audit log.")
            return redirect('verification:update_service_login')

        raw_logs = cert.query_logs.select_related('queried_by').all().order_by('-queried_at')

        # Group duplicate queries by organisation or individual employer
        grouped = {}
        for log in raw_logs:
            if log.organisation_name and log.organisation_name.strip():
                key = f"org_{log.organisation_name.strip().lower()}"
                display_name = log.organisation_name.strip()
            elif log.queried_by:
                key = f"user_{log.queried_by.pk}"
                display_name = log.queried_by.get_full_name() or log.queried_by.username
            else:
                key = "unknown_employer"
                display_name = "Registered Employer"

            if key not in grouped:
                grouped[key] = {
                    'name': display_name,
                    'count': 0,
                    'latest_log': log,
                    'logs': [],
                }
            grouped[key]['count'] += 1
            grouped[key]['logs'].append(log)

        grouped_logs = list(grouped.values())

        return render(request, self.template_name, {
            'cert': cert,
            'query_logs': grouped_logs,
            'total_checks_count': raw_logs.count(),
            'unique_employers_count': len(grouped_logs),
        })


class UpdateServiceEnrollView(View):
    """
    Initializes Paystack checkout to enroll / renew the certificate on the Update Service.
    Annual Fee: SiteSettings.price_monitoring_annual (₦3,000/yr).
    """
    def dispatch(self, request, *args, **kwargs):
        if request.user.is_authenticated and not (request.user.is_staff or request.user.is_superuser):
            if is_employer(request.user):
                messages.info(request, "Employers verify candidate certificates via the Verify Certificate tool. The Continuous Update Service is managed directly by the individual certificate holder.")
                return redirect('employer:certificate_verify')
        return super().dispatch(request, *args, **kwargs)

    def get(self, request):
        cert = _get_update_service_cert(request)
        if not cert:
            messages.info(request, "Please enter your Certificate ID, Surname, and Date of Birth first.")
            return redirect('verification:update_service_login')

        site_settings = SiteSettings.get()
        amount_naira = site_settings.price_monitoring_annual

        user = request.user if request.user.is_authenticated else cert.holder

        try:
            checkout_res = initialize_service_checkout(
                user=user,
                service='monitoring',
                tier='annual',
                amount_naira=amount_naira,
                metadata={
                    'service': 'monitoring',
                    'certificate_id': cert.certificate_id,
                }
            )
            return redirect(checkout_res['authorization_url'])
        except Exception as e:
            messages.error(request, f"Unable to initialize payment gateway: {e}")
            return redirect('verification:update_service_portal')


class UpdateServiceLogoutView(View):
    """
    Exits the Update Service guest session and redirects to the login screen.
    """
    def get(self, request):
        request.session.pop('update_service_cert_id', None)
        messages.success(request, "You have exited the Update Service.")
        return redirect('verification:update_service_login')


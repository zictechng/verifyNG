
import logging
from django.shortcuts import render, redirect, get_object_or_404
from django.views.generic import FormView, DetailView, ListView, View
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib import messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.http import HttpResponseRedirect, Http404
from django.urls import reverse

from verification.models import VerificationRequest, VerificationResult
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
from core.permissions import officer_required, is_verification_officer
from core.rate_limiting import get_client_ip

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

    def form_valid(self, form):
        ip_addr = get_client_ip(self.request)
        try:
            verif_request = create_verification_request(
                requester=self.request.user,
                subject_name=form.cleaned_data['subject_name'],
                subject_type=form.cleaned_data['subject_type'],
                verification_type=form.cleaned_data['verification_type'],
                notes=form.cleaned_data.get('notes', ''),
                identifier_type=form.cleaned_data.get('identifier_type') or None,
                identifier_value=form.cleaned_data.get('identifier_value') or None,
                ip_address=ip_addr
            )
            messages.success(
                self.request,
                f"Verification request [{verif_request.reference_number}] submitted successfully."
            )
            return redirect('verification:detail', reference_number=verif_request.reference_number)
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
            VerificationRequest.objects.select_related('target_subject', 'requester').prefetch_related('result'),
            reference_number=ref
        )
        if not can_view_verification(self.request.user, obj):
            raise PermissionDenied("You do not have authorization to view this verification record.")
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
                    complete_verification_request(
                        reference_number=reference_number,
                        officer_user=request.user,
                        outcome=form.cleaned_data['outcome'],
                        summary=form.cleaned_data['summary'],
                        details=form.cleaned_data['details_json'],
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
        if obj.status != 'completed' or not hasattr(obj, 'result'):
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




# ─────────────────────────────────────────────────────────────────────────────
# W-08: Certificate System Views
# ─────────────────────────────────────────────────────────────────────────────
from django.utils import timezone as tz
from verification.models import VerificationCertificate, CertificateQueryLog
from verification.forms import CertificateApplyForm
from verification.services import (
    create_certificate_application,
    process_certificate_query,
    get_certificate_query_price,
)


class CertificateApplyView(LoginRequiredMixin, FormView):
    """
    Authenticated user applies for a Standard or Enhanced certificate.
    Creates a VerificationCertificate in 'pending' status.
    NIN verification and activation happen via officer review (separate flow).
    """
    template_name = 'verification/certificate_apply.html'
    form_class = CertificateApplyForm

    def dispatch(self, request, *args, **kwargs):
        # Prevent duplicate active certificates
        if request.user.is_authenticated:
            existing = VerificationCertificate.objects.filter(
                holder=request.user,
                status__in=['pending', 'active']
            ).first()
            if existing:
                messages.info(
                    request,
                    f"You already have a certificate ({existing.certificate_id}). "
                    f"You cannot apply for a new one while it is active or pending."
                )
                return redirect('verification:my_certificate')
        return super().dispatch(request, *args, **kwargs)

    def form_valid(self, form):
        ip_addr = get_client_ip(self.request)
        try:
            certificate = create_certificate_application(
                holder=self.request.user,
                check_level=form.cleaned_data['check_level'],
                ip_address=ip_addr,
            )
            messages.success(
                self.request,
                f"Your application has been submitted. "
                f"Certificate ID: {certificate.certificate_id}. "
                f"You will be notified once your identity is verified."
            )
            return redirect('verification:my_certificate')
        except ValidationError as e:
            form.add_error(None, str(e))
            return self.form_invalid(form)

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['page_title'] = 'Apply for a VerifyNG Certificate'
        return ctx


class MyCertificateView(LoginRequiredMixin, View):
    """
    Certificate holder views their own certificate dashboard.
    Shows certificate status, ID, QR code, and recent query activity.
    """
    template_name = 'verification/my_certificate.html'

    def get(self, request):
        certificate = (
            VerificationCertificate.objects
            .filter(holder=request.user, is_active=True)
            .select_related('subject')
            .order_by('-created_at')
            .first()
        )
        recent_queries = []
        if certificate:
            recent_queries = (
                CertificateQueryLog.objects
                .filter(certificate=certificate)
                .select_related('queried_by')
                .order_by('-queried_at')[:5]
            )
        return render(request, self.template_name, {
            'certificate': certificate,
            'recent_queries': recent_queries,
            'page_title': 'My Certificate',
        })


class QueryLogView(LoginRequiredMixin, View):
    """
    Certificate holder views the full log of who has queried their certificate.
    Paginated. Holder can see: querier name, organisation, purpose, date.
    Holder cannot see the result_snapshot (what the querier saw).
    """
    template_name = 'verification/query_log.html'
    paginate_by = 20

    def get(self, request):
        certificate = get_object_or_404(
            VerificationCertificate,
            holder=request.user,
            is_active=True
        )
        from django.core.paginator import Paginator
        qs = (
            CertificateQueryLog.objects
            .filter(certificate=certificate)
            .select_related('queried_by')
            .order_by('-queried_at')
        )
        paginator = Paginator(qs, self.paginate_by)
        page_number = request.GET.get('page', 1)
        page_obj = paginator.get_page(page_number)

        return render(request, self.template_name, {
            'certificate': certificate,
            'page_obj': page_obj,
            'total_queries': qs.count(),
            'page_title': 'Who Checked My Certificate',
        })


class CertificateQueryView(LoginRequiredMixin, View):
    """
    An employer, landlord, or other querier enters a certificate ID and sees the result.
    Requirements before showing result:
    1. User must be logged in
    2. User must have completed payment for this query
    3. Certificate must exist
    Result is logged to CertificateQueryLog with an immutable result_snapshot.
    Shows: name, photo, status, record counts — never report details.
    """
    template_name = 'verification/certificate_query_result.html'

    def get(self, request, certificate_id):
        """
        GET: Show the query landing page with payment prompt.
        If payment already confirmed for this session, show result.
        """
        certificate = get_object_or_404(
            VerificationCertificate,
            certificate_id=certificate_id
        )
        # Check if user has already paid for this certificate in this session
        paid_transaction_id = request.session.get(
            f'cert_query_paid_{certificate_id}'
        )
        if paid_transaction_id:
            return self._render_result(request, certificate, paid_transaction_id)

        # Show payment prompt
        query_price = get_certificate_query_price(certificate.check_level)
        return render(request, 'verification/certificate_query_landing.html', {
            'certificate_id': certificate_id,
            'query_price': query_price,
            'page_title': f'Query Certificate {certificate_id}',
        })

    def post(self, request, certificate_id):
        """
        POST: Called by payment callback after successful Paystack transaction.
        Confirms payment, logs the query, shows the result.
        """
        certificate = get_object_or_404(
            VerificationCertificate,
            certificate_id=certificate_id
        )
        transaction_reference = request.POST.get('transaction_reference', '')
        ip_addr = get_client_ip(request)
        purpose = request.POST.get('purpose', 'other')
        organisation_name = request.POST.get('organisation_name', '')

        try:
            query_log = process_certificate_query(
                certificate=certificate,
                queried_by=request.user,
                transaction_reference=transaction_reference,
                ip_address=ip_addr,
                purpose=purpose,
                organisation_name=organisation_name,
            )
            # Store payment confirmation in session so GET can show result
            request.session[f'cert_query_paid_{certificate_id}'] = str(query_log.payment_id)
            return self._render_result(request, certificate, query_log.payment_id)

        except ValidationError as e:
            messages.error(request, str(e))
            return redirect('verification:certificate_query', certificate_id=certificate_id)

    def _render_result(self, request, certificate, transaction_id):
        """
        Internal: Renders the result page.
        Shows counts only — never individual report details.
        This is the controlled, data-minimised view.
        """
        # Import here to avoid circular imports — reports app wired in W-09
        fraud_count = 0
        misconduct_count = 0
        try:
            from reports.models import FraudReport
            fraud_count = FraudReport.objects.filter(
                subject=certificate.subject,
                status='verified'
            ).count()
        except Exception:
            pass  # reports app not yet linked — safe default

        return render(request, self.template_name, {
            'certificate': certificate,
            'fraud_count': fraud_count,
            'misconduct_count': misconduct_count,
            'is_valid': certificate.is_valid,
            'page_title': f'Certificate Result — {certificate.certificate_id}',
            'disclaimer': (
                "This is a VerifyNG Verification Report. "
                "It is not a government-issued certificate. "
                "VerifyNG makes no guarantee of the completeness of this record."
            ),
        })


class CertificatePDFView(LoginRequiredMixin, View):
    """
    PDF download of the certificate.
    Restricted to the certificate holder only.
    Serves via pre-signed S3 URL or generates on demand.
    """
    def get(self, request, certificate_id):
        certificate = get_object_or_404(
            VerificationCertificate,
            certificate_id=certificate_id,
            holder=request.user,       # holder only — no one else
            status='active',
        )
        if certificate.pdf_file:
            # Redirect to pre-signed S3 URL (generated in service layer)
            from verification.services import get_certificate_pdf_url
            pdf_url = get_certificate_pdf_url(certificate)
            return redirect(pdf_url)

        messages.warning(
            request,
            "Your certificate PDF is not yet ready. "
            "It will be generated once your identity is verified."
        )
        return redirect('verification:my_certificate')


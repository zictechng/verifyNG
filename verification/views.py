
import logging
from django.shortcuts import render, redirect, get_object_or_404
from django.views.generic import FormView, DetailView, ListView, View
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib import messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.http import HttpResponseRedirect, Http404, HttpResponse
from django.urls import reverse
from verification.tasks import generate_certificate_pdf
from payments.services import check_user_entitlement, consume_user_entitlement
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
from core.permissions import officer_required, is_verification_officer
from core.rate_limiting import get_client_ip
from reports.models import FraudReport
        
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
        allowed, reason, details = check_user_entitlement(self.request.user, service='verification')
        if not allowed:
            messages.error(
                self.request,
                "An active subscription or verified entitlement is required to request identity & document verifications. "
                "Please upgrade your plan to continue."
            )
            return redirect('payments:plans')
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
            consume_user_entitlement(self.request.user, service='verification')
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



# ============================================================
# W-08: Certificate views
# ============================================================

class CertificateApplyView(LoginRequiredMixin, View):
    """
    Multi-step TrustPass Background Clearance application wizard (DBS-style).
    Applicants apply directly for their employment or enhanced clearance certificate.
    """
    template_name = 'verification/certificate_apply.html'
    def get(self, request):
        user = request.user
        initial = {
            'full_name': user.get_full_name().strip() or user.username,
            'email': user.email or '',
            'check_level': request.GET.get('level', 'employment'),
        }
        form = CertificateApplyForm(initial=initial)
        return render(request, self.template_name, {'form': form})
    def post(self, request):
        form = CertificateApplyForm(request.POST, request.FILES)
        if not form.is_valid():
            return render(request, self.template_name, {'form': form})
        cd = form.cleaned_data
        ip_addr = get_client_ip(request)
        try:
            certificate = create_trustpass_certificate_application(
                holder=request.user,
                full_name=cd['full_name'],
                check_level=cd.get('check_level') or cd.get('certificate_type') or 'employment',
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
                ip_address=ip_addr,
            )
            messages.success(
                request,
                f"Your TrustPass Clearance Application [{certificate.certificate_id}] has been submitted successfully for verification review."
            )
            return redirect('verification:my_certificate', certificate_id=certificate.certificate_id)
        except ValidationError as e:
            form.add_error(None, e.message if hasattr(e, 'message') else str(e))
            return render(request, self.template_name, {'form': form})


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
        base_url = request.build_absolute_uri('/')[:-1]
        pdf_bytes = generate_certificate_pdf_bytes(cert, base_url=base_url)
        response = HttpResponse(pdf_bytes, content_type='application/pdf')
        response['Content-Disposition'] = f'attachment; filename="VerifyNG_Certificate_{cert.certificate_id}.pdf"'
        return response
    

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
        from payments.models import Transaction

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



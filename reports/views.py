import logging
from django.shortcuts import render, redirect, get_object_or_404
from django.views.generic import FormView, DetailView, View, TemplateView, ListView
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.http import FileResponse, Http404, HttpResponseRedirect

from reports.forms import (
    FraudReportSubmissionForm,
    DisputeSubmissionForm,
    ReportModerationActionForm,
    DisputeResolutionForm,
)
from reports.models import FraudReport, ReportEvidence, Dispute
from reports.services import (
    create_fraud_report,
    transition_report_state,
    file_dispute_for_report,
    resolve_dispute,
)
from reports.storage_services import get_storage_service_for_provider, StorageError
from core.permissions import can_view_report, can_view_evidence, is_moderator
from core.rate_limiting import get_client_ip

logger = logging.getLogger(__name__)

class ReportCreateView(LoginRequiredMixin, FormView):
    """Authenticated view for submitting a new fraud report."""
    form_class = FraudReportSubmissionForm
    template_name = 'reports/create_report.html'

    def dispatch(self, request, *args, **kwargs):
        # LoginRequiredMixin handles unauthenticated users via super().
        # For authenticated-but-unverified users, block here before form renders.
        if request.user.is_authenticated and not request.user.identity_verified:
            messages.warning(
                request,
                "You must verify your identity (NIN or BVN) before submitting a fraud report. "
                "Please complete identity verification first."
            )
            return redirect('verification:create')
        return super().dispatch(request, *args, **kwargs)

    def form_valid(self, form):
        try:
            report = create_fraud_report(
                reporter=self.request.user,
                subject_name=form.cleaned_data['subject_name'],
                subject_type=form.cleaned_data['subject_type'],
                title=form.cleaned_data['title'],
                allegation=form.cleaned_data['allegation'],
                incident_date=form.cleaned_data.get('incident_date'),
                evidence_file=form.cleaned_data.get('evidence_file'),
                evidence_type=form.cleaned_data.get('evidence_type'),
                evidence_description=form.cleaned_data.get('evidence_description', ''),
                suspect_phone=form.cleaned_data.get('suspect_phone'),
                suspect_bank_account=form.cleaned_data.get('suspect_bank_account'),
                suspect_bank_name=form.cleaned_data.get('suspect_bank_name'),
                suspect_cac_number=form.cleaned_data.get('suspect_cac_number'),
                suspect_email=form.cleaned_data.get('suspect_email'),
                suspect_location=form.cleaned_data.get('suspect_location'),
                suspect_state=form.cleaned_data.get('suspect_state'),
                suspect_city=form.cleaned_data.get('suspect_city'),
            )
            return redirect('reports:detail', reference_number=report.reference_number)
        except StorageError as e:
            logger.error("ReportCreateView: StorageError during submission: %s", str(e))
            form.add_error(
                'evidence_file',
                "Evidence file upload failed. Please verify storage settings or try uploading again."
            )
            return self.form_invalid(form)

class MyReportsListView(LoginRequiredMixin, ListView):
    """
    Dedicated view for authenticated citizens/reporters to list,
    track, and add further documentary evidence to their submitted fraud reports.
    """
    model = FraudReport
    template_name = 'reports/my_reports.html'
    context_object_name = 'reports'
    paginate_by = 15

    def get_queryset(self):
        return (
            FraudReport.objects.filter(reporter=self.request.user)
            .select_related('target_subject')
            .prefetch_related('evidence_files')
            .order_by('-created_at')
        )

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        base_qs = FraudReport.objects.filter(reporter=self.request.user)
        ctx['total_count'] = base_qs.count()
        ctx['review_count'] = base_qs.filter(state__in=['submitted', 'under_review']).count()
        ctx['published_count'] = base_qs.filter(state='published').count()
        ctx['resolved_count'] = base_qs.filter(state__in=['resolved', 'disputed']).count()
        return ctx


class ReportDetailView(DetailView):
    """Public/reporter/moderator view for a single fraud report."""
    model = FraudReport
    template_name = 'reports/report_detail.html'
    context_object_name = 'report'

    def get_object(self, queryset=None):
        ref = self.kwargs.get('reference_number')
        report = get_object_or_404(FraudReport, reference_number=ref)
        if not can_view_report(self.request.user, report):
            raise PermissionDenied("You do not have permission to view this report.")
        return report

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['is_moderator'] = is_moderator(self.request.user)
        ctx['can_dispute'] = (
            self.request.user.is_authenticated
            and self.object.state == 'published'
        )
        # Extract suspect context from initial audit log if present
        init_log = self.object.audit_logs.filter(action="REPORT_SUBMITTED").first()
        if init_log and isinstance(init_log.details, dict):
            ctx['suspect_context'] = init_log.details.get('suspect_context', {})
        else:
            ctx['suspect_context'] = {}
        return ctx

class EvidenceDownloadView(View):
    """
    Secure evidence download view.
    Enforces can_view_evidence() RBAC check before ANY file access.
    Routes Cloudinary evidence through signed private URLs.
    Routes local evidence through Django FileResponse.
    """
    def get(self, request, evidence_id):
        evidence = get_object_or_404(ReportEvidence, id=evidence_id)

        if not can_view_evidence(request.user, evidence):
            raise PermissionDenied("You do not have permission to access this evidence file.")

        provider = evidence.storage_provider or 'local'

        if provider == 'local':
            if not evidence.file:
                raise Http404("Evidence file reference is missing.")
            try:
                if not evidence.file.storage.exists(evidence.file.name):
                    raise Http404("Evidence file not found in local storage.")
                return FileResponse(evidence.file.open('rb'), as_attachment=True)
            except Http404:
                raise
            except Exception as e:
                logger.error("Local evidence file open failed: %s", type(e).__name__)
                raise Http404("Evidence file could not be served.")

        if not evidence.storage_public_id or not evidence.storage_resource_type or not evidence.storage_format:
            logger.error("Cloud evidence record id=%s missing storage metadata.", evidence.id)
            raise Http404("Evidence file metadata is incomplete.")

        try:
            storage = get_storage_service_for_provider(provider)
            signed_url = storage.generate_signed_url(
                public_id=evidence.storage_public_id,
                format=evidence.storage_format,
                resource_type=evidence.storage_resource_type,
                expires_in_seconds=300
            )
            return HttpResponseRedirect(signed_url)
        except StorageError as e:
            logger.error("Evidence download StorageError for id=%s: %s", evidence.id, str(e))
            raise Http404("Evidence file could not be retrieved at this time.")


class EvidenceUploadView(LoginRequiredMixin, View):
    """
    Allows the original reporter to upload additional evidence files
    to their own report, provided it is still in an open state.
    Allowed states: submitted, under_review.
    """
    ALLOWED_STATES = {'submitted', 'under_review'}
    ALLOWED_MIME_TYPES = {
        'image/jpeg', 'image/png', 'image/webp',
        'application/pdf',
    }
    MAX_FILE_SIZE_BYTES = 10 * 1024 * 1024  # 10 MB

    def post(self, request, reference_number):
        report = get_object_or_404(FraudReport, reference_number=reference_number)

        # Ownership check
        if report.reporter != request.user:
            raise PermissionDenied("You do not have permission to add evidence to this report.")

        # State check
        if report.state not in self.ALLOWED_STATES:
            messages.error(request, "Evidence can only be added while the report is under review.")
            return HttpResponseRedirect(report.get_absolute_url() if hasattr(report, 'get_absolute_url') else f'/reports/{reference_number}/')

        uploaded_file = request.FILES.get('evidence_file')
        if not uploaded_file:
            messages.error(request, "Please select a file to upload.")
            return HttpResponseRedirect(f'/reports/{reference_number}/')

        # File size check
        if uploaded_file.size > self.MAX_FILE_SIZE_BYTES:
            messages.error(request, "File size must be 10 MB or less.")
            return HttpResponseRedirect(f'/reports/{reference_number}/')

        # MIME type check
        if uploaded_file.content_type not in self.ALLOWED_MIME_TYPES:
            messages.error(request, "Only JPEG, PNG, WebP images and PDF files are accepted.")
            return HttpResponseRedirect(f'/reports/{reference_number}/')

        file_type = request.POST.get('file_type', 'other')
        description = request.POST.get('description', '').strip()[:255]

        ReportEvidence.objects.create(
            report=report,
            file=uploaded_file,
            file_type=file_type,
            description=description,
            is_confidential=True,
            storage_provider='local',
        )

        messages.success(request, "Evidence uploaded successfully.")
        return HttpResponseRedirect(f'/reports/{reference_number}/')


class SubjectPhotoUploadView(LoginRequiredMixin, View):
    """
    Allows the original reporter to upload a single photo of the subject
    (scammer/person named in the report), displayed on the report detail card.
    Replaces any existing subject photo.
    Allowed states: submitted, under_review.
    """
    ALLOWED_STATES = {'submitted', 'under_review'}
    ALLOWED_MIME_TYPES = {'image/jpeg', 'image/png', 'image/webp'}
    MAX_FILE_SIZE_BYTES = 5 * 1024 * 1024  # 5 MB

    def post(self, request, reference_number):
        report = get_object_or_404(FraudReport, reference_number=reference_number)

        # Ownership check
        if report.reporter != request.user:
            raise PermissionDenied("You do not have permission to update this report.")

        # State check
        if report.state not in self.ALLOWED_STATES:
            messages.error(request, "The subject photo can only be updated while the report is under review.")
            return HttpResponseRedirect(f'/reports/{reference_number}/')

        uploaded_file = request.FILES.get('subject_photo')
        if not uploaded_file:
            messages.error(request, "Please select a photo to upload.")
            return HttpResponseRedirect(f'/reports/{reference_number}/')

        # File size check
        if uploaded_file.size > self.MAX_FILE_SIZE_BYTES:
            messages.error(request, "Photo must be 5 MB or less.")
            return HttpResponseRedirect(f'/reports/{reference_number}/')

        # MIME type check
        if uploaded_file.content_type not in self.ALLOWED_MIME_TYPES:
            messages.error(request, "Only JPEG, PNG, or WebP images are accepted for the subject photo.")
            return HttpResponseRedirect(f'/reports/{reference_number}/')

        subject = report.target_subject
        # Delete old photo file from storage before replacing
        if subject.photo:
            subject.photo.delete(save=False)

        subject.photo = uploaded_file
        subject.save(update_fields=['photo'])

        messages.success(request, "Subject photo uploaded successfully.")
        return HttpResponseRedirect(f'/reports/{reference_number}/')


class DisputeCreateView(LoginRequiredMixin, FormView):
    """View for filing a right-of-response dispute against a published report."""
    form_class = DisputeSubmissionForm
    template_name = 'reports/dispute_form.html'

    def dispatch(self, request, *args, **kwargs):
        self.report = get_object_or_404(FraudReport, reference_number=kwargs['reference_number'])
        # Allow employee response/dispute during 7-day fair-hearing notice or when published
        if self.report.state not in ('published', 'submitted', 'under_review'):
            messages.error(request, f"This report is currently {self.report.get_state_display().lower()} and cannot be disputed.")
            return redirect('reports:detail', reference_number=self.report.reference_number)
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['report'] = self.report
        return ctx

    def form_valid(self, form):
        ip_addr = get_client_ip(self.request)
        file_dispute_for_report(
            report=self.report,
            disputant=self.request.user,
            reason=form.cleaned_data['reason'],
            counter_evidence=form.cleaned_data.get('counter_evidence'),
            ip_address=ip_addr
        )
        messages.success(self.request, f"Dispute submitted successfully for report {self.report.reference_number}.")
        return redirect('reports:detail', reference_number=self.report.reference_number)


class ModerationQueueView(LoginRequiredMixin, UserPassesTestMixin, TemplateView):
    """Moderator desk: lists reports and disputes awaiting review."""
    template_name = 'reports/moderation_queue.html'

    def test_func(self):
        return is_moderator(self.request.user)

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['pending_reports'] = (
            FraudReport.objects.filter(state__in=['submitted', 'under_review'])
            .select_related('target_subject', 'reporter')
            .order_by('-created_at')
        )
        ctx['published_reports'] = (
            FraudReport.objects.filter(state='published')
            .select_related('target_subject', 'reporter')
            .order_by('-created_at')[:20]
        )
        ctx['open_disputes'] = (
            Dispute.objects.filter(status__in=['opened', 'under_review'])
            .select_related('report', 'disputant', 'report__target_subject')
            .order_by('-created_at')
        )
        ctx['moderation_form'] = ReportModerationActionForm()
        ctx['resolution_form'] = DisputeResolutionForm()
        return ctx


class ReportModerationTransitionView(LoginRequiredMixin, UserPassesTestMixin, View):
    """Moderator action handler for transitioning a report's lifecycle state."""
    def test_func(self):
        return is_moderator(self.request.user)

    def post(self, request, reference_number):
        report = get_object_or_404(FraudReport, reference_number=reference_number)
        form = ReportModerationActionForm(request.POST)
        if form.is_valid():
            action = form.cleaned_data['action']
            notes = form.cleaned_data.get('moderation_notes', '')
            ip_addr = get_client_ip(request)

            transition_report_state(
                report=report,
                new_state=action,
                actor=request.user,
                ip_address=ip_addr,
                moderation_notes=notes
            )
            messages.success(request, f"Report {report.reference_number} transitioned to {action.upper()}.")
        else:
            for error_list in form.errors.values():
                for error in error_list:
                    messages.error(request, error)

        return redirect('reports:moderation_queue')


class DisputeResolveView(LoginRequiredMixin, UserPassesTestMixin, View):
    """Moderator action handler for adjudicating an open dispute."""
    def test_func(self):
        return is_moderator(self.request.user)

    def post(self, request, dispute_id):
        dispute = get_object_or_404(Dispute, id=dispute_id)
        form = DisputeResolutionForm(request.POST)
        if form.is_valid():
            resolution = form.cleaned_data['resolution']
            notes = form.cleaned_data['resolution_notes']
            ip_addr = get_client_ip(request)

            resolve_dispute(
                dispute=dispute,
                outcome=resolution,
                actor=request.user,
                resolution_notes=notes,
                ip_address=ip_addr
            )
            messages.success(request, f"Dispute #{dispute.id} was {resolution.upper()}.")
        else:
            for error_list in form.errors.values():
                for error in error_list:
                    messages.error(request, error)

        return redirect('reports:moderation_queue')

import logging
from django.shortcuts import render, redirect, get_object_or_404
from django.views.generic import FormView, DetailView, View, TemplateView, ListView
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.http import FileResponse, Http404, HttpResponseRedirect
from django.urls import reverse

from reports.forms import (
    FraudReportSubmissionForm,
    DisputeSubmissionForm,
    ReportModerationActionForm,
    DisputeResolutionForm,
    ComplainantRebuttalForm,
    ModeratorInfoRequestForm,
    InfoRequestFulfillForm,
)
from reports.models import FraudReport, ReportEvidence, Dispute
from reports.services import (
    create_fraud_report,
    transition_report_state,
    file_dispute_for_report,
    resolve_dispute,
    submit_complainant_rebuttal,
    issue_moderator_info_request,
    fulfill_moderator_info_request,
)
from reports.storage_services import get_storage_service_for_provider, StorageError
from core.permissions import can_view_report, can_view_evidence, is_moderator, get_user_home_url
from core.rate_limiting import get_client_ip

logger = logging.getLogger(__name__)

class ReportCreateView(LoginRequiredMixin, FormView):
    """Authenticated view for submitting a new fraud report."""
    form_class = FraudReportSubmissionForm
    template_name = 'reports/create_report.html'

    def dispatch(self, request, *args, **kwargs):
        # LoginRequiredMixin handles unauthenticated users via super().
        if request.user.is_authenticated:
            from payments.services import check_user_entitlement
            allowed, reason, details = check_user_entitlement(request.user, service='fraud_report')
            if not allowed and reason == 'service_restricted':
                messages.error(
                    request,
                    details.get('message', "Access to Fraud Crime Reporting has been restricted for your account by platform administration.")
                )
                return redirect(get_user_home_url(request.user))

            from core.permissions import is_profile_verified
            verified, v_msg = is_profile_verified(request.user)
            if not verified:
                messages.warning(
                    request,
                    v_msg or "You must verify your identity (NIN or BVN) before submitting a fraud report."
                )
                return redirect(reverse('users:profile') + '?tab=verification')
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



class MyDisputesListView(LoginRequiredMixin, ListView):
    """
    Lists all reports and allegations filed against the authenticated user or their entity.
    Provides clear visibility into 7-day fair-hearing notices, dispute statuses, and response actions.
    """
    model = FraudReport
    template_name = 'reports/my_disputes.html'
    context_object_name = 'reports'
    paginate_by = 15

    def get_queryset(self):
        from reports.services import get_reports_against_user_queryset
        from django.db.models import Q
        qs = get_reports_against_user_queryset(self.request.user)

        status_filter = self.request.GET.get('status', '').strip()
        search_query = self.request.GET.get('q', '').strip()

        if status_filter == 'action_required':
            user_disputed_report_ids = Dispute.objects.filter(disputant=self.request.user).values_list('report_id', flat=True)
            qs = qs.filter(state__in=['submitted', 'under_review', 'published']).exclude(id__in=user_disputed_report_ids)
        elif status_filter == 'disputed':
            user_disputed_report_ids = Dispute.objects.filter(disputant=self.request.user).values_list('report_id', flat=True)
            qs = qs.filter(id__in=user_disputed_report_ids)
        elif status_filter in ('resolved', 'rejected', 'restricted'):
            qs = qs.filter(state__in=['resolved', 'restricted'])

        if search_query:
            qs = qs.filter(
                Q(reference_number__icontains=search_query) |
                Q(title__icontains=search_query) |
                Q(allegation__icontains=search_query)
            )

        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        from reports.services import get_reports_against_user_queryset
        base_qs = get_reports_against_user_queryset(self.request.user)
        user_disputes = Dispute.objects.filter(disputant=self.request.user)
        disputed_ids = set(user_disputes.values_list('report_id', flat=True))

        ctx['total_count'] = base_qs.count()
        ctx['action_required_count'] = base_qs.filter(state__in=['submitted', 'under_review', 'published']).exclude(id__in=disputed_ids).count()
        ctx['disputed_count'] = base_qs.filter(id__in=disputed_ids).count()
        ctx['resolved_count'] = base_qs.filter(state__in=['resolved', 'restricted']).count()
        ctx['status_filter'] = self.request.GET.get('status', '').strip()
        ctx['search_query'] = self.request.GET.get('q', '').strip()
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
        user_has_disputed = (
            self.request.user.is_authenticated
            and self.object.disputes.filter(disputant=self.request.user).exists()
        )
        ctx['user_has_disputed'] = user_has_disputed
        ctx['can_dispute'] = (
            self.request.user.is_authenticated
            and self.request.user != self.object.reporter
            and self.object.complainant_rebuttal is None
            and not user_has_disputed
            and (
                self.object.state in ('published', 'submitted', 'under_review', 'disputed')
            )
        )
        ctx['disputes'] = self.object.disputes.all().select_related('disputant').order_by('created_at')
        # Extract suspect context from initial audit log if present
        init_log = self.object.audit_logs.filter(action="REPORT_SUBMITTED").first()
        if init_log and isinstance(init_log.details, dict):
            ctx['suspect_context'] = init_log.details.get('suspect_context', {})
        else:
            ctx['suspect_context'] = {}

        # Determine context-aware back navigation
        src = self.request.GET.get('src', '').strip()
        referer = self.request.META.get('HTTP_REFERER', '')
        user = self.request.user

        if src == 'misconduct' or '/employer/misconduct' in referer:
            back_url = reverse('employer:staff_misconduct_list')
            back_label = "Misconduct Reports"
        elif src == 'my_reports' or '/reports/my-reports' in referer:
            back_url = reverse('reports:my_reports')
            back_label = "My Submitted Reports"
        elif src == 'admin' or '/admin-portal' in referer:
            back_url = reverse('admin_portal:overview')
            back_label = "Admin Portal"
        elif self.object.is_misconduct:
            if user.is_authenticated and (getattr(user, 'role', '') in ('employer', 'agency', 'business') or user.is_staff):
                back_url = reverse('employer:staff_misconduct_list')
                back_label = "Misconduct Reports"
            elif user.is_authenticated:
                back_url = reverse('dashboard:index')
                back_label = "Dashboard"
            else:
                back_url = reverse('home')
                back_label = "Home"
        else:
            if user.is_authenticated:
                if user.is_superuser or user.is_staff or getattr(user, 'role', '') in ('moderator', 'officer'):
                    back_url = reverse('admin_portal:overview')
                    back_label = "Admin Portal"
                else:
                    back_url = reverse('reports:my_reports')
                    back_label = "My Submitted Reports"
            else:
                back_url = reverse('home')
                back_label = "Home"

        ctx['back_url'] = back_url
        ctx['back_label'] = back_label

        # Due Process: Rebuttal & Interlocutory Info Requests context
        ctx['complainant_rebuttal'] = self.object.complainant_rebuttal
        ctx['can_submit_rebuttal'] = self.object.can_submit_rebuttal and (self.request.user == self.object.reporter)
        ctx['pending_info_request'] = self.object.pending_info_request_for_user(self.request.user)
        ctx['moderator_info_requests'] = self.object.moderator_info_requests if is_moderator(self.request.user) else []
        ctx['fulfill_form'] = InfoRequestFulfillForm()
        if is_moderator(self.request.user):
            ctx['info_request_form'] = ModeratorInfoRequestForm()

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
        as_attachment = request.GET.get('download') == '1'

        if provider == 'local':
            if not evidence.file:
                raise Http404("Evidence file reference is missing.")
            try:
                if not evidence.file.storage.exists(evidence.file.name):
                    raise Http404("Evidence file not found in local storage.")
                response = FileResponse(evidence.file.open('rb'), as_attachment=as_attachment)
                response['X-Frame-Options'] = 'SAMEORIGIN'
                return response
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
                expires_in_seconds=300,
                attachment=as_attachment
            )
            return HttpResponseRedirect(signed_url)
        except StorageError as e:
            logger.error("Evidence download StorageError for id=%s: %s", evidence.id, str(e))
            raise Http404("Evidence file could not be retrieved at this time.")


class DisputeCounterEvidenceView(LoginRequiredMixin, View):
    """
    Safely serves counter-evidence uploaded by the accused party in a dispute.
    Accessible to administrators, moderators, the disputant, and the original reporter.
    """
    def get(self, request, dispute_id):
        dispute = get_object_or_404(
            Dispute.objects.select_related('report', 'disputant', 'report__reporter'),
            id=dispute_id
        )

        is_staff_or_mod = is_moderator(request.user)
        is_party = (request.user == dispute.disputant or request.user == dispute.report.reporter)
        if not (is_staff_or_mod or is_party):
            raise PermissionDenied("You do not have permission to view this counter-evidence.")

        if not dispute.counter_evidence:
            raise Http404("No counter-evidence file was attached to this dispute.")

        as_attachment = request.GET.get('download') == '1'
        try:
            if hasattr(dispute.counter_evidence, 'storage') and not dispute.counter_evidence.storage.exists(dispute.counter_evidence.name):
                raise Http404("Counter-evidence file not found on storage.")
            response = FileResponse(dispute.counter_evidence.open('rb'), as_attachment=as_attachment)
            response['X-Frame-Options'] = 'SAMEORIGIN'
            return response
        except Http404:
            raise
        except Exception as e:
            logger.error("Failed to serve counter-evidence for dispute id=%s: %s", dispute_id, e)
            raise Http404("Could not read counter-evidence file.")



class EvidenceUploadView(LoginRequiredMixin, View):
    """
    Allows the original reporter to upload additional evidence files
    to their own report, provided it is still in an open state.
    Allowed states: submitted, under_review.
    """
    ALLOWED_STATES = {'submitted', 'under_review', 'disputed'}
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
            messages.error(request, "Evidence can only be added while the report is under review or disputed.")
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
        if request.user.is_authenticated:
            from core.permissions import is_profile_verified
            verified, v_msg = is_profile_verified(request.user)
            if not verified:
                messages.warning(
                    request,
                    v_msg or "You must verify your identity before submitting an official dispute affidavit."
                )
                return redirect(reverse('users:profile') + '?tab=verification')
        self.report = get_object_or_404(FraudReport, reference_number=kwargs['reference_number'])
        # Disallow reporter from disputing their own report
        if request.user.is_authenticated and self.report.reporter == request.user:
            messages.warning(request, "You cannot file a right-of-response dispute against a report you submitted.")
            return redirect('reports:detail', reference_number=self.report.reference_number)
        # Disallow dispute if pleadings are closed following complainant final rebuttal
        if self.report.complainant_rebuttal is not None:
            messages.warning(
                request,
                "Pleadings are officially closed on this report following the complainant's final rebuttal. "
                "The case is currently under compliance adjudication."
            )
            return redirect('reports:detail', reference_number=self.report.reference_number)
        # Disallow second dispute if respondent already submitted their defense (Strict 1-shot)
        if request.user.is_authenticated and self.report.disputes.filter(disputant=request.user).exists():
            messages.warning(
                request,
                "You have already submitted your defense statement for this report. "
                "Additional evidence can only be submitted if requested by a compliance moderator."
            )
            return redirect('reports:detail', reference_number=self.report.reference_number)
        # Allow employee response/dispute during 7-day fair-hearing notice, when published, or subsequent addenda while disputed
        if self.report.state not in ('published', 'submitted', 'under_review', 'disputed'):
            messages.error(request, f"This report is currently {self.report.get_state_display().lower()} and cannot be disputed.")
            return redirect('reports:detail', reference_number=self.report.reference_number)
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['report'] = self.report
        ctx['existing_disputes'] = self.report.disputes.all().select_related('disputant').order_by('created_at')
        init_log = self.report.audit_logs.filter(action="REPORT_SUBMITTED").first()
        if init_log and isinstance(init_log.details, dict):
            ctx['suspect_context'] = init_log.details.get('suspect_context', {})
        else:
            ctx['suspect_context'] = {}
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


class RebuttalCreateView(LoginRequiredMixin, FormView):
    """
    Form view allowing the original complainant (Party A) to submit a formal 1-time
    rebuttal and counter-evidence in response to the respondent's defense statement.
    Enforces equality of arms and closes pleadings for final adjudication.
    """
    form_class = ComplainantRebuttalForm
    template_name = 'reports/rebuttal_form.html'

    def dispatch(self, request, *args, **kwargs):
        if request.user.is_authenticated:
            from core.permissions import is_profile_verified
            verified, v_msg = is_profile_verified(request.user)
            if not verified:
                messages.warning(
                    request,
                    v_msg or "You must verify your identity before submitting an official dispute affidavit."
                )
                return redirect(reverse('users:profile') + '?tab=verification')
        self.report = get_object_or_404(FraudReport, reference_number=kwargs['reference_number'])
        if self.report.reporter != request.user:
            messages.warning(request, "Only the original complainant can submit a rebuttal on this report.")
            return redirect('reports:detail', reference_number=self.report.reference_number)
        if not self.report.can_submit_rebuttal:
            messages.warning(request, "A rebuttal cannot be submitted for this report at this time.")
            return redirect('reports:detail', reference_number=self.report.reference_number)
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['report'] = self.report
        ctx['disputes'] = self.report.disputes.all().select_related('disputant').order_by('created_at')
        init_log = self.report.audit_logs.filter(action="REPORT_SUBMITTED").first()
        if init_log and isinstance(init_log.details, dict):
            ctx['suspect_context'] = init_log.details.get('suspect_context', {})
        else:
            ctx['suspect_context'] = {}
        return ctx

    def form_valid(self, form):
        ip_addr = get_client_ip(self.request)
        try:
            submit_complainant_rebuttal(
                report=self.report,
                reporter=self.request.user,
                rebuttal_statement=form.cleaned_data['rebuttal_statement'],
                evidence_file=form.cleaned_data.get('rebuttal_evidence'),
                ip_address=ip_addr
            )
            messages.success(
                self.request,
                f"Your formal rebuttal for report {self.report.reference_number} has been recorded. "
                "Pleadings are now closed and the case is pending compliance adjudication."
            )
        except Exception as e:
            logger.error("Failed to submit rebuttal for %s: %s", self.report.reference_number, e)
            messages.error(self.request, f"Could not submit rebuttal: {e}")
        return redirect('reports:detail', reference_number=self.report.reference_number)


class ModeratorInfoRequestView(LoginRequiredMixin, UserPassesTestMixin, View):
    """
    Allows a compliance moderator to issue an interlocutory information request
    to either the complainant or respondent during report adjudication.
    """
    def test_func(self):
        return is_moderator(self.request.user)

    def post(self, request, reference_number):
        report = get_object_or_404(FraudReport, reference_number=reference_number)
        form = ModeratorInfoRequestForm(request.POST)
        if form.is_valid():
            target_role = form.cleaned_data['target_role']
            title = form.cleaned_data.get('title')
            message = form.cleaned_data['message']
            ip_addr = get_client_ip(request)

            try:
                issue_moderator_info_request(
                    report=report,
                    moderator=request.user,
                    target_role=target_role,
                    message=message,
                    request_title=title,
                    ip_address=ip_addr,
                )
                messages.success(request, f"Information request dispatched to {target_role.capitalize()}.")
            except Exception as e:
                logger.error("Failed to issue info request on %s: %s", report.reference_number, e)
                messages.error(request, f"Could not dispatch request: {e}")
        else:
            for error_list in form.errors.values():
                for error in error_list:
                    messages.error(request, error)

        referer = request.META.get('HTTP_REFERER')
        if referer:
            return HttpResponseRedirect(referer)
        return redirect('reports:detail', reference_number=reference_number)


class InfoRequestFulfillView(LoginRequiredMixin, View):
    """
    Allows a requested party (complainant or respondent) to fulfill
    an active compliance moderator information request.
    """
    def post(self, request, reference_number, request_id):
        report = get_object_or_404(FraudReport, reference_number=reference_number)
        form = InfoRequestFulfillForm(request.POST, request.FILES)
        if form.is_valid():
            statement = form.cleaned_data['response_statement']
            file = form.cleaned_data.get('response_file')
            ip_addr = get_client_ip(request)

            try:
                fulfill_moderator_info_request(
                    report=report,
                    user=request.user,
                    request_id=request_id,
                    response_statement=statement,
                    evidence_file=file,
                    ip_address=ip_addr,
                )
                messages.success(request, "Your clarification and documents have been submitted to compliance moderators.")
            except Exception as e:
                logger.error("Failed to fulfill info request %s on %s: %s", request_id, reference_number, e)
                messages.error(request, f"Could not submit response: {e}")
        else:
            for error_list in form.errors.values():
                for error in error_list:
                    messages.error(request, error)

        return redirect('reports:detail', reference_number=reference_number)



import json
import logging
from datetime import timedelta
from django.utils import timezone
from django.shortcuts import render, redirect, get_object_or_404
from django.views.generic import TemplateView, View
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.contrib import messages
from django.db.models import Count
from django.db import connection
from django.core.cache import cache

from users.models import User, LoginAudit
from reports.models import FraudReport, Dispute, AuditLog
from verification.models import VerificationRequest
from identities.models import Identifier, SubjectEntity
from core.permissions import is_superadmin
from core.tasks import send_email_notification_task

from django.core.paginator import Paginator
from django.http import HttpResponseForbidden
from django.conf import settings
import os

# Import models needed for extended admin
try:
    from reports.models import Dispute
except ImportError:
    Dispute = None

try:
    from verification.models import VerificationRequest, VerificationCertificate
except ImportError:
    VerificationRequest = None
    VerificationCertificate = None

try:
    from employer.models import EmployerProfile
except ImportError:
    EmployerProfile = None

try:
    from payments.models import Subscription, Plan, SiteSettings, PlatformConfiguration
except ImportError:
    Subscription = None
    Plan = None
    SiteSettings = None
    PlatformConfiguration = None

logger = logging.getLogger(__name__)


class SuperAdminRequiredMixin(LoginRequiredMixin, UserPassesTestMixin):
    """Enforces that only superusers or staff members can access the Admin Portal."""
    def test_func(self):
        return is_superadmin(self.request.user)


class AdminOverviewView(SuperAdminRequiredMixin, TemplateView):
    """Executive Admin Portal Dashboard: KPIs, 7-Day Activity Trends, System Health."""
    template_name = "admin_portal/overview.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        now = timezone.now()
        seven_days_ago = now - timedelta(days=7)

        # 1. Platform KPI Metrics
        ctx['total_users'] = User.objects.count()
        ctx['active_users'] = User.objects.filter(is_active=True).count()
        ctx['suspended_users'] = User.objects.filter(is_active=False).count()
        ctx['total_reports'] = FraudReport.objects.count()
        ctx['pending_reports'] = FraudReport.objects.filter(state__in=['submitted', 'under_review']).count()
        ctx['published_reports'] = FraudReport.objects.filter(state='published').count()
        ctx['open_disputes'] = Dispute.objects.filter(status__in=['opened', 'under_review']).count()
        ctx['total_verifications'] = VerificationRequest.objects.count()
        ctx['pending_verifications'] = VerificationRequest.objects.filter(status__in=['pending', 'in_progress']).count()
        ctx['total_identifiers'] = Identifier.objects.count()

        # 2. System Health Diagnostics
        db_healthy = False
        try:
            with connection.cursor() as cursor:
                cursor.execute("SELECT 1")
                db_healthy = True
        except Exception:
            db_healthy = False
        ctx['db_healthy'] = db_healthy

        redis_healthy = False
        try:
            cache.set("admin_healthcheck", "ok", 10)
            redis_healthy = cache.get("admin_healthcheck") == "ok"
        except Exception:
            redis_healthy = False
        ctx['redis_healthy'] = redis_healthy

        # 3. 7-Day Chart.js Trend Series
        labels = []
        user_reg_data = []
        reports_data = []
        verifications_data = []

        for i in range(6, -1, -1):
            day_start = (now - timedelta(days=i)).replace(hour=0, minute=0, second=0, microsecond=0)
            day_end = day_start + timedelta(days=1)
            day_label = day_start.strftime("%b %d")
            labels.append(day_label)

            u_count = User.objects.filter(date_joined__gte=day_start, date_joined__lt=day_end).count()
            r_count = FraudReport.objects.filter(created_at__gte=day_start, created_at__lt=day_end).count()
            v_count = VerificationRequest.objects.filter(created_at__gte=day_start, created_at__lt=day_end).count()

            user_reg_data.append(u_count)
            reports_data.append(r_count)
            verifications_data.append(v_count)

        ctx['chart_labels_json'] = json.dumps(labels)
        ctx['chart_users_json'] = json.dumps(user_reg_data)
        ctx['chart_reports_json'] = json.dumps(reports_data)
        ctx['chart_verifications_json'] = json.dumps(verifications_data)

        # 4. Recent Security & Login Events
        ctx['recent_logins'] = LoginAudit.objects.select_related('user')[:8]

        return ctx


class AdminUserListView(SuperAdminRequiredMixin, TemplateView):
    """User Management Desk: Search, Role Filtering, Status Toggle, Role Reassignment."""
    template_name = "admin_portal/users.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        query = self.request.GET.get('q', '').strip()
        role_filter = self.request.GET.get('role', '')
        status_filter = self.request.GET.get('status', '')

        users = User.objects.all().order_by('-date_joined')

        if query:
            users = users.filter(username__icontains=query) | users.filter(email__icontains=query)

        if role_filter:
            users = users.filter(role=role_filter)

        if status_filter == 'active':
            users = users.filter(is_active=True)
        elif status_filter == 'suspended':
            users = users.filter(is_active=False)

        ctx['users_list'] = users[:50]
        ctx['role_choices'] = User.ROLE_CHOICES
        ctx['query'] = query
        ctx['selected_role'] = role_filter
        ctx['selected_status'] = status_filter
        return ctx


class AdminUserToggleStatusView(SuperAdminRequiredMixin, View):
    """Suspends or Reactivates a user account."""
    def post(self, request, user_id):
        target_user = get_object_or_404(User, id=user_id)
        if target_user == request.user:
            messages.error(request, "You cannot suspend your own superuser account.")
            return redirect('admin_portal:users')

        new_status = not target_user.is_active
        target_user.is_active = new_status
        target_user.save(update_fields=['is_active'])

        action_name = "Activated" if new_status else "Suspended"
        messages.success(request, f"User '{target_user.username}' has been successfully {action_name}.")

        AuditLog.objects.create(
            action=f"ADMIN_USER_{action_name.upper()}",
            performed_by=request.user,
            details={"target_user_id": target_user.id, "target_username": target_user.username}
        )
        return redirect('admin_portal:users')


class AdminUserChangeRoleView(SuperAdminRequiredMixin, View):
    """Reassigns a user's role (e.g. Moderator, Verification Officer, Business)."""
    def post(self, request, user_id):
        target_user = get_object_or_404(User, id=user_id)
        new_role = request.POST.get('role')
        valid_roles = dict(User.ROLE_CHOICES)

        if new_role not in valid_roles:
            messages.error(request, f"Invalid role '{new_role}'.")
            return redirect('admin_portal:users')

        old_role = target_user.role
        target_user.role = new_role
        target_user.save(update_fields=['role'])

        messages.success(request, f"Updated '{target_user.username}' role from {old_role} to {valid_roles[new_role]}.")

        AuditLog.objects.create(
            action="ADMIN_USER_ROLE_CHANGE",
            performed_by=request.user,
            details={
                "target_user_id": target_user.id,
                "target_username": target_user.username,
                "old_role": old_role,
                "new_role": new_role
            }
        )
        return redirect('admin_portal:users')


class AdminAuditLogsView(SuperAdminRequiredMixin, TemplateView):
    """System & Security Audit Log Explorer: IP, System/OS, Location, Outcomes."""
    template_name = "admin_portal/audit_logs.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        status_filter = self.request.GET.get('status', '')
        search_query = self.request.GET.get('q', '').strip()

        logs = LoginAudit.objects.select_related('user').all()

        if status_filter:
            logs = logs.filter(status=status_filter)

        if search_query:
            logs = logs.filter(username_attempted__icontains=search_query) | logs.filter(ip_address__icontains=search_query)

        ctx['logs'] = logs[:100]
        ctx['selected_status'] = status_filter
        ctx['search_query'] = search_query
        return ctx


class AdminCommunicationsView(SuperAdminRequiredMixin, TemplateView):
    """Email Broadcasting and Targeted Message Dispatch Center."""
    template_name = "admin_portal/communications.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['roles'] = User.ROLE_CHOICES
        return ctx

    def post(self, request, *args, **kwargs):
        target_type = request.POST.get('target_type')  # 'all', 'role', 'single'
        subject = request.POST.get('subject', '').strip()
        message_body = request.POST.get('message_body', '').strip()
        target_role = request.POST.get('target_role')
        target_email = request.POST.get('target_email', '').strip()

        if not subject or not message_body:
            messages.error(request, "Subject and Message Body are mandatory fields.")
            return render(request, self.template_name, self.get_context_data())

        recipient_emails = []

        if target_type == 'single':
            if not target_email or '@' not in target_email:
                messages.error(request, "Please enter a valid single recipient email address.")
                return render(request, self.template_name, self.get_context_data())
            recipient_emails = [target_email]

        elif target_type == 'role':
            users = User.objects.filter(role=target_role, is_active=True).exclude(email='').values_list('email', flat=True)
            recipient_emails = list(users)

        elif target_type == 'all':
            users = User.objects.filter(is_active=True).exclude(email='').values_list('email', flat=True)
            recipient_emails = list(users)

        if not recipient_emails:
            messages.warning(request, "No active recipients matched your target criteria.")
            return redirect('admin_portal:communications')

        # Dispatch each email via asynchronous Celery task
        for email in recipient_emails:
            send_email_notification_task.delay(email, subject, message_body)

        messages.success(
            request,
            f"Successfully queued {len(recipient_emails)} email notification(s) for background dispatch via Celery."
        )

        AuditLog.objects.create(
            action="ADMIN_EMAIL_BROADCAST",
            performed_by=request.user,
            details={
                "target_type": target_type,
                "target_role": target_role if target_type == 'role' else None,
                "recipients_count": len(recipient_emails),
                "subject": subject
            }
        )
        return redirect('admin_portal:communications')


# ============================================================
# ADMIN PORTAL — Extended Views
# Append below existing views in dashboard/admin_views.py
# ============================================================

# ── User Detail + Hard Delete + Block ─────────────────────────────────────

class AdminUserDetailView(SuperAdminRequiredMixin, TemplateView):
    """Full user profile: all fields, login history, reports, verifications, subscriptions."""
    template_name = "admin_portal/user_detail.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        target_user = get_object_or_404(User, id=self.kwargs['user_id'])
        ctx['target_user'] = target_user
        ctx['role_choices'] = User.ROLE_CHOICES
        ctx['login_history'] = LoginAudit.objects.filter(user=target_user).order_by('-timestamp')[:20]
        ctx['user_reports'] = FraudReport.objects.filter(reporter=target_user).order_by('-created_at')[:10]
        ctx['user_verifications'] = VerificationRequest.objects.filter(requester=target_user).order_by('-created_at')[:10] if VerificationRequest else []
        ctx['user_audit_logs'] = AuditLog.objects.filter(performed_by=target_user).order_by('-timestamp')[:20]
        if Subscription:
            ctx['user_subscriptions'] = Subscription.objects.filter(user=target_user).order_by('-created_at')[:5]
        else:
            ctx['user_subscriptions'] = []
        return ctx


class AdminUserHardDeleteView(SuperAdminRequiredMixin, View):
    """Permanently deletes a user and all their data. Requires confirmation token."""
    def post(self, request, user_id):
        target_user = get_object_or_404(User, id=user_id)
        if target_user == request.user:
            messages.error(request, "You cannot delete your own superuser account.")
            return redirect('admin_portal:users')

        confirm = request.POST.get('confirm_delete', '').strip()
        if confirm != target_user.username:
            messages.error(request, "Confirmation username did not match. Hard delete cancelled.")
            return redirect('admin_portal:user_detail', user_id=user_id)

        username = target_user.username
        AuditLog.objects.create(
            action="ADMIN_USER_HARD_DELETE",
            performed_by=request.user,
            details={"deleted_user_id": target_user.id, "deleted_username": username}
        )
        target_user.delete()
        messages.success(request, f"User '{username}' and all associated data permanently deleted.")
        return redirect('admin_portal:users')


class AdminUserBlockView(SuperAdminRequiredMixin, View):
    """Blocks a user (deactivates + marks staff=False, strips role to 'individual')."""
    def post(self, request, user_id):
        target_user = get_object_or_404(User, id=user_id)
        if target_user == request.user:
            messages.error(request, "You cannot block your own account.")
            return redirect('admin_portal:user_detail', user_id=user_id)

        action = request.POST.get('action', 'block')
        if action == 'block':
            target_user.is_active = False
            target_user.is_staff = False
            target_user.save(update_fields=['is_active', 'is_staff'])
            AuditLog.objects.create(
                action="ADMIN_USER_BLOCKED",
                performed_by=request.user,
                details={"target_user_id": target_user.id, "target_username": target_user.username}
            )
            messages.success(request, f"User '{target_user.username}' has been blocked.")
        elif action == 'unblock':
            target_user.is_active = True
            target_user.save(update_fields=['is_active'])
            AuditLog.objects.create(
                action="ADMIN_USER_UNBLOCKED",
                performed_by=request.user,
                details={"target_user_id": target_user.id, "target_username": target_user.username}
            )
            messages.success(request, f"User '{target_user.username}' has been unblocked.")
        return redirect('admin_portal:user_detail', user_id=user_id)


# ── Reports Moderation ─────────────────────────────────────────────────────

class AdminReportsView(SuperAdminRequiredMixin, TemplateView):
    """Full fraud report moderation queue with filtering and pagination."""
    template_name = "admin_portal/reports.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        state_filter = self.request.GET.get('state', '')
        q = self.request.GET.get('q', '').strip()

        reports = FraudReport.objects.select_related('reporter', 'target_subject').order_by('-created_at')

        if state_filter:
            reports = reports.filter(state=state_filter)
        if q:
            reports = reports.filter(reference_number__icontains=q) | \
                      reports.filter(title__icontains=q) | \
                      reports.filter(reporter__username__icontains=q)

        paginator = Paginator(reports, 25)
        page = self.request.GET.get('page', 1)
        ctx['page_obj'] = paginator.get_page(page)
        ctx['state_choices'] = FraudReport.STATES
        ctx['selected_state'] = state_filter
        ctx['q'] = q
        ctx['counts'] = {s[0]: FraudReport.objects.filter(state=s[0]).count() for s in FraudReport.STATES}
        return ctx


class AdminReportDetailView(SuperAdminRequiredMixin, TemplateView):
    """Full detail view for a single fraud report: evidence, audit trail, state actions."""
    template_name = "admin_portal/report_detail.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        report = get_object_or_404(
            FraudReport.objects.select_related('reporter', 'target_subject'),
            pk=self.kwargs['pk']
        )
        ctx['report'] = report
        ctx['evidence_list'] = report.evidence_files.all()
        ctx['disputes'] = report.disputes.order_by('-created_at') if hasattr(report, 'disputes') else []
        ctx['audit_trail'] = AuditLog.objects.filter(
            details__contains=str(report.id)
        ).order_by('-timestamp')[:20]
        ctx['state_choices'] = FraudReport.STATES
        return ctx


class AdminReportTransitionView(SuperAdminRequiredMixin, View):
    """POST handler: transitions a report to a new state."""
    VALID_TRANSITIONS = {
        'submitted': ['under_review', 'rejected'],
        'under_review': ['published', 'rejected', 'restricted', 'archived'],
        'published': ['disputed', 'archived', 'restricted'],
        'disputed': ['resolved', 'published', 'restricted'],
        'resolved': ['archived'],
        'rejected': ['archived'],
        'restricted': ['published', 'archived'],
        'archived': [],
    }

    def post(self, request, pk):
        report = get_object_or_404(FraudReport, pk=pk)
        new_state = request.POST.get('new_state', '').strip()
        moderation_notes = request.POST.get('moderation_notes', '').strip()

        allowed = self.VALID_TRANSITIONS.get(report.state, [])
        if new_state not in allowed:
            messages.error(request, f"Cannot transition from '{report.state}' to '{new_state}'.")
            return redirect('admin_portal:report_detail', pk=pk)

        old_state = report.state
        report.state = new_state
        if moderation_notes:
            report.moderation_notes = moderation_notes
        report.save(update_fields=['state', 'moderation_notes', 'updated_at'])

        AuditLog.objects.create(
            action="ADMIN_REPORT_STATE_CHANGE",
            performed_by=request.user,
            details={
                "report_id": report.id,
                "reference": report.reference_number,
                "old_state": old_state,
                "new_state": new_state,
            }
        )
        messages.success(request, f"Report {report.reference_number} transitioned from '{old_state}' → '{new_state}'.")
        return redirect('admin_portal:report_detail', pk=pk)


# ── Disputes ───────────────────────────────────────────────────────────────

class AdminDisputesView(SuperAdminRequiredMixin, TemplateView):
    """Disputes management queue."""
    template_name = "admin_portal/disputes.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        status_filter = self.request.GET.get('status', '')
        q = self.request.GET.get('q', '').strip()

        disputes = Dispute.objects.select_related('report', 'disputed_by').order_by('-created_at') if Dispute else Dispute.objects.none()

        if status_filter:
            disputes = disputes.filter(status=status_filter)
        if q:
            disputes = disputes.filter(report__reference_number__icontains=q)

        paginator = Paginator(disputes, 25)
        ctx['page_obj'] = paginator.get_page(self.request.GET.get('page', 1))
        ctx['status_choices'] = Dispute.DISPUTE_STATES if Dispute else []
        ctx['selected_status'] = status_filter
        return ctx


class AdminDisputeActionView(SuperAdminRequiredMixin, View):
    """POST: Accept (uphold) or Reject a dispute."""
    def post(self, request, pk):
        dispute = get_object_or_404(Dispute, pk=pk)
        action = request.POST.get('action', '')
        resolution_notes = request.POST.get('resolution_notes', '').strip()

        if action == 'accept':
            dispute.status = 'upheld'
            dispute.report.state = 'resolved'
            dispute.report.save(update_fields=['state', 'updated_at'])
        elif action == 'reject':
            dispute.status = 'rejected'
            dispute.report.state = 'published'
            dispute.report.save(update_fields=['state', 'updated_at'])
        else:
            messages.error(request, "Invalid dispute action.")
            return redirect('admin_portal:disputes')

        dispute.resolution_notes = resolution_notes
        dispute.save()

        AuditLog.objects.create(
            action=f"ADMIN_DISPUTE_{action.upper()}",
            performed_by=request.user,
            details={"dispute_id": dispute.id, "report_ref": dispute.report.reference_number}
        )
        messages.success(request, f"Dispute {action}ed successfully.")
        return redirect('admin_portal:disputes')


# ── Verifications ──────────────────────────────────────────────────────────

class AdminVerificationsView(SuperAdminRequiredMixin, TemplateView):
    """Verifications request queue."""
    template_name = "admin_portal/verifications.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        status_filter = self.request.GET.get('status', '')
        type_filter = self.request.GET.get('type', '')

        qs = VerificationRequest.objects.select_related('requester', 'target_subject').order_by('-created_at') if VerificationRequest else []

        if status_filter and qs:
            qs = qs.filter(status=status_filter)
        if type_filter and qs:
            qs = qs.filter(verification_type=type_filter)

        paginator = Paginator(qs, 25)
        ctx['page_obj'] = paginator.get_page(self.request.GET.get('page', 1))
        ctx['status_choices'] = VerificationRequest.STATUS_CHOICES if VerificationRequest else []
        ctx['type_choices'] = VerificationRequest.VERIFICATION_TYPES if VerificationRequest else []
        ctx['selected_status'] = status_filter
        ctx['selected_type'] = type_filter
        return ctx


class AdminVerificationActionView(SuperAdminRequiredMixin, View):
    """POST: complete or reject a verification request."""
    def post(self, request, pk):
        req = get_object_or_404(VerificationRequest, pk=pk)
        action = request.POST.get('action', '')
        notes = request.POST.get('notes', '').strip()

        if action == 'complete':
            req.status = 'completed'
        elif action == 'reject':
            req.status = 'rejected'
        elif action == 'in_progress':
            req.status = 'in_progress'
        else:
            messages.error(request, "Invalid action.")
            return redirect('admin_portal:verifications')

        req.notes = notes
        req.save(update_fields=['status', 'notes', 'updated_at'])

        AuditLog.objects.create(
            action=f"ADMIN_VERIFICATION_{action.upper()}",
            performed_by=request.user,
            details={"verification_id": req.id, "reference": req.reference_number}
        )
        messages.success(request, f"Verification {req.reference_number} marked as '{action}'.")
        return redirect('admin_portal:verifications')


# ── Employer Profiles ──────────────────────────────────────────────────────

class AdminEmployerProfilesView(SuperAdminRequiredMixin, TemplateView):
    """All employer profiles — verify, suspend, view."""
    template_name = "admin_portal/employer_profiles.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        q = self.request.GET.get('q', '').strip()
        verified_filter = self.request.GET.get('verified', '')

        if EmployerProfile:
            qs = EmployerProfile.objects.select_related('user').order_by('-created_at')
            if q:
                qs = qs.filter(company_name__icontains=q) | qs.filter(user__email__icontains=q)
            if verified_filter == 'yes':
                qs = qs.filter(is_verified=True)
            elif verified_filter == 'no':
                qs = qs.filter(is_verified=False)
            paginator = Paginator(qs, 25)
            ctx['page_obj'] = paginator.get_page(self.request.GET.get('page', 1))
        else:
            ctx['page_obj'] = []
        ctx['q'] = q
        ctx['verified_filter'] = verified_filter
        return ctx


class AdminEmployerActionView(SuperAdminRequiredMixin, View):
    """POST: verify or unverify an employer profile."""
    def post(self, request, pk):
        profile = get_object_or_404(EmployerProfile, pk=pk)
        action = request.POST.get('action', '')

        if action == 'verify':
            profile.is_verified = True
            profile.save(update_fields=['is_verified'])
            msg = f"Employer '{profile.company_name}' verified."
        elif action == 'unverify':
            profile.is_verified = False
            profile.save(update_fields=['is_verified'])
            msg = f"Employer '{profile.company_name}' unverified."
        elif action == 'suspend':
            profile.user.is_active = False
            profile.user.save(update_fields=['is_active'])
            msg = f"Employer account '{profile.company_name}' suspended."
        else:
            messages.error(request, "Invalid action.")
            return redirect('admin_portal:employer_profiles')

        AuditLog.objects.create(
            action=f"ADMIN_EMPLOYER_{action.upper()}",
            performed_by=request.user,
            details={"employer_profile_id": profile.id, "company": profile.company_name}
        )
        messages.success(request, msg)
        return redirect('admin_portal:employer_profiles')


# ── Subscriptions ──────────────────────────────────────────────────────────

class AdminSubscriptionsView(SuperAdminRequiredMixin, TemplateView):
    """All subscriptions management."""
    template_name = "admin_portal/subscriptions.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        status_filter = self.request.GET.get('status', '')
        q = self.request.GET.get('q', '').strip()

        if Subscription:
            qs = Subscription.objects.select_related('user', 'plan').order_by('-created_at')
            if status_filter:
                qs = qs.filter(status=status_filter)
            if q:
                qs = qs.filter(user__email__icontains=q) | qs.filter(user__username__icontains=q)
            paginator = Paginator(qs, 25)
            ctx['page_obj'] = paginator.get_page(self.request.GET.get('page', 1))
            ctx['status_choices'] = Subscription.STATUS_CHOICES
        else:
            ctx['page_obj'] = []
            ctx['status_choices'] = []
        ctx['selected_status'] = status_filter
        ctx['q'] = q
        return ctx


class AdminSubscriptionCancelView(SuperAdminRequiredMixin, View):
    """POST: cancel a subscription."""
    def post(self, request, pk):
        sub = get_object_or_404(Subscription, pk=pk)
        reason = request.POST.get('reason', 'Admin cancellation').strip()
        sub.status = 'cancelled'
        sub.save(update_fields=['status'])
        AuditLog.objects.create(
            action="ADMIN_SUBSCRIPTION_CANCEL",
            performed_by=request.user,
            details={"subscription_id": sub.id, "user": sub.user.username, "reason": reason}
        )
        messages.success(request, f"Subscription for '{sub.user.username}' cancelled.")
        return redirect('admin_portal:subscriptions')


# ── Analytics ─────────────────────────────────────────────────────────────

class AdminAnalyticsView(SuperAdminRequiredMixin, TemplateView):
    """Platform-wide analytics: user growth, report trends, revenue, verifications."""
    template_name = "admin_portal/analytics.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        now = timezone.now()
        thirty_days_ago = now - timedelta(days=30)

        # 30-day daily series
        labels, user_series, report_series, verif_series = [], [], [], []
        for i in range(29, -1, -1):
            d_start = (now - timedelta(days=i)).replace(hour=0, minute=0, second=0, microsecond=0)
            d_end = d_start + timedelta(days=1)
            labels.append(d_start.strftime("%b %d"))
            user_series.append(User.objects.filter(date_joined__gte=d_start, date_joined__lt=d_end).count())
            report_series.append(FraudReport.objects.filter(created_at__gte=d_start, created_at__lt=d_end).count())
            verif_series.append(VerificationRequest.objects.filter(created_at__gte=d_start, created_at__lt=d_end).count() if VerificationRequest else 0)

        ctx['chart_labels'] = json.dumps(labels)
        ctx['chart_users'] = json.dumps(user_series)
        ctx['chart_reports'] = json.dumps(report_series)
        ctx['chart_verifications'] = json.dumps(verif_series)

        # Role distribution
        role_dist = {r[0]: User.objects.filter(role=r[0]).count() for r in User.ROLE_CHOICES}
        ctx['role_labels'] = json.dumps(list(role_dist.keys()))
        ctx['role_counts'] = json.dumps(list(role_dist.values()))

        # Report state breakdown
        state_dist = {s[0]: FraudReport.objects.filter(state=s[0]).count() for s in FraudReport.STATES}
        ctx['state_labels'] = json.dumps([s[1] for s in FraudReport.STATES])
        ctx['state_counts'] = json.dumps([state_dist[s[0]] for s in FraudReport.STATES])

        # Top-line KPIs
        ctx['new_users_30d'] = User.objects.filter(date_joined__gte=thirty_days_ago).count()
        ctx['new_reports_30d'] = FraudReport.objects.filter(created_at__gte=thirty_days_ago).count()
        ctx['verified_users_total'] = User.objects.filter(identity_verified=True).count()

        # Subscription revenue (if available)
        if Subscription:
            from django.db.models import Sum
            active_subs = Subscription.objects.filter(status='active')
            ctx['active_subscriptions'] = active_subs.count()
        else:
            ctx['active_subscriptions'] = 0

        return ctx


# ── System Logs ────────────────────────────────────────────────────────────

class AdminSystemLogsView(SuperAdminRequiredMixin, TemplateView):
    """All AuditLog records — full system event trail."""
    template_name = "admin_portal/system_logs.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        action_filter = self.request.GET.get('action', '').strip()
        q = self.request.GET.get('q', '').strip()

        logs = AuditLog.objects.select_related('performed_by').order_by('-timestamp')

        if action_filter:
            logs = logs.filter(action__icontains=action_filter)
        if q:
            logs = logs.filter(performed_by__username__icontains=q)

        # Distinct action types for filter dropdown
        ctx['action_types'] = AuditLog.objects.values_list('action', flat=True).distinct().order_by('action')[:50]

        paginator = Paginator(logs, 50)
        ctx['page_obj'] = paginator.get_page(self.request.GET.get('page', 1))
        ctx['action_filter'] = action_filter
        ctx['q'] = q
        return ctx


class AdminActivityLogsView(SuperAdminRequiredMixin, TemplateView):
    """Recent platform activity across users — report submissions, verifications, logins."""
    template_name = "admin_portal/activity_logs.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        now = timezone.now()

        ctx['recent_reports'] = FraudReport.objects.select_related('reporter').order_by('-created_at')[:30]
        ctx['recent_verifications'] = VerificationRequest.objects.select_related('requester').order_by('-created_at')[:30] if VerificationRequest else []
        ctx['recent_users'] = User.objects.order_by('-date_joined')[:20]
        ctx['recent_audit'] = AuditLog.objects.select_related('performed_by').order_by('-timestamp')[:50]
        return ctx


class AdminLoginLogsView(SuperAdminRequiredMixin, TemplateView):
    """Dedicated login log explorer — full SearchFilter, IP, device, location."""
    template_name = "admin_portal/login_logs.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        status_filter = self.request.GET.get('status', '')
        q = self.request.GET.get('q', '').strip()
        ip_filter = self.request.GET.get('ip', '').strip()

        logs = LoginAudit.objects.select_related('user').order_by('-timestamp')

        if status_filter:
            logs = logs.filter(status=status_filter)
        if q:
            logs = logs.filter(username_attempted__icontains=q)
        if ip_filter:
            logs = logs.filter(ip_address__icontains=ip_filter)

        # Stats
        ctx['total_logins'] = LoginAudit.objects.count()
        ctx['failed_logins'] = LoginAudit.objects.filter(status='failed').count()
        ctx['blocked_logins'] = LoginAudit.objects.filter(status='blocked').count()
        ctx['success_logins'] = LoginAudit.objects.filter(status='success').count()

        paginator = Paginator(logs, 50)
        ctx['page_obj'] = paginator.get_page(self.request.GET.get('page', 1))
        ctx['status_choices'] = LoginAudit.STATUS_CHOICES
        ctx['selected_status'] = status_filter
        ctx['q'] = q
        ctx['ip_filter'] = ip_filter
        return ctx


# ── Platform Settings ──────────────────────────────────────────────────────

class AdminPlatformSettingsView(SuperAdminRequiredMixin, TemplateView):
    """Platform branding configuration: logo, favicon, company name, social links."""
    template_name = "admin_portal/platform_settings.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['config'] = PlatformConfiguration.get() if PlatformConfiguration else None
        return ctx

    def post(self, request, *args, **kwargs):
        if not PlatformConfiguration:
            messages.error(request, "PlatformConfiguration model not available.")
            return redirect('admin_portal:platform_settings')

        config = PlatformConfiguration.get()

        # Text fields
        config.platform_name = request.POST.get('platform_name', config.platform_name).strip()
        config.tagline = request.POST.get('tagline', config.tagline).strip()
        config.company_name = request.POST.get('company_name', config.company_name).strip()
        config.company_reg_number = request.POST.get('company_reg_number', config.company_reg_number).strip()
        config.support_email = request.POST.get('support_email', config.support_email).strip()
        config.contact_phone = request.POST.get('contact_phone', config.contact_phone).strip()
        config.contact_address = request.POST.get('contact_address', config.contact_address).strip()
        config.twitter_url = request.POST.get('twitter_url', config.twitter_url).strip()
        config.instagram_url = request.POST.get('instagram_url', config.instagram_url).strip()
        config.facebook_url = request.POST.get('facebook_url', config.facebook_url).strip()
        config.linkedin_url = request.POST.get('linkedin_url', config.linkedin_url).strip()
        config.whatsapp_number = request.POST.get('whatsapp_number', config.whatsapp_number).strip()
        config.meta_description = request.POST.get('meta_description', config.meta_description).strip()
        config.meta_keywords = request.POST.get('meta_keywords', config.meta_keywords).strip()
        config.footer_copyright_text = request.POST.get('footer_copyright_text', config.footer_copyright_text).strip()
        config.maintenance_mode = request.POST.get('maintenance_mode') == 'on'
        config.maintenance_message = request.POST.get('maintenance_message', config.maintenance_message).strip()

        # File uploads
        if 'logo' in request.FILES:
            config.logo = request.FILES['logo']
        if 'favicon' in request.FILES:
            config.favicon = request.FILES['favicon']

        config.updated_by = request.user
        config.save()

        AuditLog.objects.create(
            action="ADMIN_PLATFORM_CONFIG_UPDATE",
            performed_by=request.user,
            details={"platform_name": config.platform_name}
        )
        messages.success(request, "Platform configuration saved successfully.")
        return redirect('admin_portal:platform_settings')


class AdminSiteSettingsView(SuperAdminRequiredMixin, TemplateView):
    """Free-tier check limits and payment system settings (SiteSettings singleton)."""
    template_name = "admin_portal/site_settings.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['settings_obj'] = SiteSettings.get() if SiteSettings else None
        if Plan:
            ctx['plans'] = Plan.objects.all().order_by('price_kobo')
        return ctx

    def post(self, request, *args, **kwargs):
        if not SiteSettings:
            messages.error(request, "SiteSettings not available.")
            return redirect('admin_portal:site_settings')

        site = SiteSettings.get()
        try:
            site.free_check_limit = int(request.POST.get('free_check_limit', site.free_check_limit))
            site.free_check_window_days = int(request.POST.get('free_check_window_days', site.free_check_window_days))
        except ValueError:
            messages.error(request, "Limits must be whole numbers.")
            return redirect('admin_portal:site_settings')

        site.maintenance_mode = request.POST.get('maintenance_mode') == 'on'
        site.save()

        AuditLog.objects.create(
            action="ADMIN_SITE_SETTINGS_UPDATE",
            performed_by=request.user,
            details={"free_check_limit": site.free_check_limit}
        )
        messages.success(request, "Site settings updated.")
        return redirect('admin_portal:site_settings')



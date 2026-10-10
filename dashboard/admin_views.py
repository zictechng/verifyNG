
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


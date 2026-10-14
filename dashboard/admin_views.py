
import json
import json as _json
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
from django.db.models import Q
from django.db import models as db_models
from reports.models import FraudReport, Dispute, AuditLog
from verification.models import VerificationRequest
from identities.models import Identifier, SubjectEntity
from core.permissions import is_superadmin
from core.tasks import send_email_notification_task
from django.db.models import Q
from core.email_utils import render_email
from notifications.tasks import send_broadcast_email_task
from django.http import JsonResponse
from django.utils import timezone as tz

from users.models import User, LoginAudit, UserServiceAccess
from core.audit_utils import log_admin_action
from django.utils.text import slugify
from payments.models import PlanFeature, Transaction

from django.core.paginator import Paginator
from django.http import HttpResponseForbidden
from django.conf import settings
from django.shortcuts import render as drender
from django.db import transaction as db_transaction
from django.db import transaction

import os
from users.models import UserServiceAccess
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
    from employer.models import EmployerProfile, TeamMember
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
        ctx['active_users'] = User.objects.filter(is_active=True, is_suspended=False).count()
        ctx['suspended_users'] = User.objects.filter(is_suspended=True, is_active=True).count()
        ctx['blocked_users'] = User.objects.filter(is_active=False).count()
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

        # 5. Quick-action data for shortcut cards
        ctx['pending_reports_qs'] = FraudReport.objects.filter(
            state__in=['submitted', 'under_review']
        ).order_by('-created_at')[:5]
        ctx['open_disputes_qs'] = Dispute.objects.filter(
            status__in=['opened', 'under_review']
        ).select_related('report', 'disputant').order_by('-created_at')[:5]
        ctx['pending_verifications_qs'] = VerificationRequest.objects.filter(
            status__in=['pending', 'in_progress']
        ).select_related('requester').order_by('-created_at')[:5] if VerificationRequest else []
        ctx['recent_users_qs'] = User.objects.order_by('-date_joined')[:5]

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
            users = users.filter(is_active=True, is_suspended=False)
        elif status_filter == 'suspended':
            users = users.filter(is_suspended=True, is_active=True)
        elif status_filter == 'blocked':
            users = users.filter(is_active=False)

        per_page = int(self.request.GET.get('per_page', 15))
        if per_page not in (15, 25, 50, 100):
            per_page = 15
        paginator = Paginator(users, per_page)
        ctx['page_obj'] = paginator.get_page(self.request.GET.get('page', 1))
        ctx['per_page'] = per_page
        ctx['per_page_options'] = [15, 25, 50, 100]
        ctx['role_choices'] = User.ROLE_CHOICES
        ctx['query'] = query
        ctx['selected_role'] = role_filter
        ctx['selected_status'] = status_filter
        return ctx

class AdminUserToggleStatusView(SuperAdminRequiredMixin, View):
    """Suspends or reactivates a user account.

    Suspension is a soft action: the user can still log in but is blocked
    from performing any platform actions by SuspendedUserMiddleware.
    This is semantically different from blocking (is_active=False) which
    prevents login entirely.
    """

    def post(self, request, public_id):
        target_user = get_object_or_404(User, public_id=public_id)

        if target_user == request.user:
            messages.error(request, "You cannot suspend your own account.")
            return redirect('admin_portal:user_detail', public_id=public_id)

        # Toggle is_suspended (NOT is_active)
        new_suspended = not target_user.is_suspended
        target_user.is_suspended = new_suspended
        target_user.save(update_fields=['is_suspended'])

        if new_suspended:
            action_label = "suspended"
            email_heading = "Your Account Has Been Suspended"
            email_body = (
                f"<p>Your VerifyNG account (<strong>{target_user.email}</strong>) "
                f"has been <strong>suspended</strong> by an administrator.</p>"
                f"<p>While your account is suspended, you can still sign in but "
                f"you will not be able to perform any actions on the platform.</p>"
                f"<p>If you believe this is an error, please contact our support team.</p>"
            )
            audit_action = "ADMIN_USER_SUSPENDED"
        else:
            action_label = "reactivated"
            email_heading = "Your Account Has Been Reactivated"
            email_body = (
                f"<p>Good news! Your VerifyNG account (<strong>{target_user.email}</strong>) "
                f"suspension has been <strong>lifted</strong> by an administrator.</p>"
                f"<p>You now have full access to the platform again.</p>"
            )
            audit_action = "ADMIN_USER_REACTIVATED"

        # Send email notification to user
        try:
            html_body, text_body = render_email('generic_notification', {
                'user_name': target_user.get_full_name() or target_user.username,
                'heading': email_heading,
                'body_html': email_body,
                'subject': email_heading,
            })
            send_broadcast_email_task.delay(
                to_email=target_user.email,
                subject=email_heading,
                html_body=html_body,
                text_body=text_body,
            )
        except Exception as exc:
            logger.warning("Failed to send suspension email to %s: %s", target_user.email, exc)

        AuditLog.objects.create(
            action=audit_action,
            performed_by=request.user,
            details={
                "target_public_id": str(target_user.public_id),
                "target_username": target_user.username,
            }
        )
        messages.success(request, f"User '{target_user.username}' has been {action_label}.")
        return redirect('admin_portal:user_detail', public_id=public_id)


class AdminUserChangeRoleView(SuperAdminRequiredMixin, View):
    """Reassigns a user's role (e.g. Moderator, Verification Officer, Business)."""
    def post(self, request, public_id):
        target_user = get_object_or_404(User, public_id=self.kwargs['public_id'])
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
                "target_public_id": target_user.id,
                "target_username": target_user.username,
                "old_role": old_role,
                "new_role": new_role
            }
        )
        return redirect('admin_portal:users')

class AdminAuditLogsView(SuperAdminRequiredMixin, TemplateView):
    """Platform-wide admin action audit log with filter, search and pagination."""
    template_name = "admin_portal/audit_logs.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)

        action_type_filter = self.request.GET.get('action_type', '').strip()
        search_query       = self.request.GET.get('q', '').strip()
        date_from          = self.request.GET.get('date_from', '').strip()
        date_to            = self.request.GET.get('date_to', '').strip()

        qs = AuditLog.objects.select_related(
            'performed_by', 'target_user', 'report'
        ).order_by('-timestamp')

        if action_type_filter:
            qs = qs.filter(action_type=action_type_filter)

        if search_query:
            qs = qs.filter(
                Q(action__icontains=search_query)          |
                Q(performed_by__username__icontains=search_query) |
                Q(target_user__username__icontains=search_query)  |
                Q(ip_address__icontains=search_query)
            )

        if date_from:
            try:
                from datetime import datetime
                qs = qs.filter(timestamp__date__gte=datetime.strptime(date_from, '%Y-%m-%d').date())
            except ValueError:
                pass

        if date_to:
            try:
                from datetime import datetime
                qs = qs.filter(timestamp__date__lte=datetime.strptime(date_to, '%Y-%m-%d').date())
            except ValueError:
                pass

        per_page = int(self.request.GET.get('per_page', 25))
        if per_page not in (25, 50, 100):
            per_page = 25

        paginator = Paginator(qs, per_page)
        ctx['page_obj']          = paginator.get_page(self.request.GET.get('page', 1))
        ctx['per_page']          = per_page
        ctx['per_page_options']  = [25, 50, 100]
        ctx['action_type_filter']= action_type_filter
        ctx['search_query']      = search_query
        ctx['date_from']         = date_from
        ctx['date_to']           = date_to
        ctx['action_type_choices'] = AuditLog.ACTION_TYPE_CHOICES
        ctx['total_count']       = paginator.count
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
        target_user = get_object_or_404(User, public_id=self.kwargs['public_id'])
        ctx['target_user'] = target_user
        ctx['role_choices'] = User.ROLE_CHOICES

        # Inside the view's get() method, add to ctx:
        service_rules = UserServiceAccess.objects.filter(user=target_user)
        service_access_rules_json = json.dumps([
            {'service': r.service, 'is_restricted': r.is_restricted}
            for r in service_rules
        ])

        ctx['service_access_rules'] = service_rules
        ctx['service_access_rules_json'] = service_access_rules_json
        ctx['service_choices'] = UserServiceAccess.SERVICE_CHOICES

        # Login history — paginated
        login_qs = LoginAudit.objects.filter(user=target_user).order_by('-timestamp')
        login_paginator = Paginator(login_qs, 15)
        ctx['login_history'] = login_paginator.get_page(
            self.request.GET.get('login_page', 1)
        )

        # System activity (AuditLog) — paginated
        
        activity_qs = AuditLog.objects.filter(performed_by=target_user).order_by('-timestamp')
        activity_paginator = Paginator(activity_qs, 15)
        ctx['user_activity'] = activity_paginator.get_page(
            self.request.GET.get('activity_page', 1)
        )

        # Active tab (preserved across pagination clicks)
        ctx['active_tab'] = self.request.GET.get('tab', 'login')

        # Other sections — keep as slices (not paginated, shown in full)
                # Reports — paginated (10 per page)
        reports_qs = FraudReport.objects.filter(
            reporter=target_user).order_by('-created_at')
        ctx['user_reports'] = Paginator(reports_qs, 10).get_page(
            self.request.GET.get('reports_page', 1)
        )

        # Verifications — paginated (10 per page)
        if VerificationRequest:
            verif_qs = VerificationRequest.objects.filter(
                requester=target_user).order_by('-created_at')
            ctx['user_verifications'] = Paginator(verif_qs, 10).get_page(
                self.request.GET.get('verif_page', 1)
            )
        else:
            ctx['user_verifications'] = []

        # Subscriptions — small number expected, keep as slice
        if Subscription:
            ctx['user_subscriptions'] = Subscription.objects.filter(
                user=target_user).order_by('-created_at')[:5]
        else:
            ctx['user_subscriptions'] = []

        # Available plans for credit subscription modal
        if Plan:
            ctx['available_plans'] = Plan.objects.filter(is_active=True).order_by('display_order', 'price_kobo')
            # Pass current active plan ID so modal can warn on duplicate selection
            active_sub = Subscription.objects.filter(
                user=target_user, status='active'
            ).select_related('plan').first()
            ctx['user_active_plan_id'] = active_sub.plan.pk if active_sub else None
        else:
            ctx['available_plans'] = []
            ctx['user_active_plan_id'] = None
        return ctx


class AdminUserActivityExportView(SuperAdminRequiredMixin, View):
    """
    Generates a printable HTML activity statement for a user.
    ?type=login|activity  &date_from=YYYY-MM-DD  &date_to=YYYY-MM-DD
    """
    def get(self, request, public_id):
        from django.utils.dateparse import parse_date
        from django.utils import timezone as tz
        import datetime

        target_user = get_object_or_404(User, public_id=self.kwargs['public_id'])
        export_type = request.GET.get('type', 'login')  # 'login' or 'activity'

        date_from_str = request.GET.get('date_from', '')
        date_to_str   = request.GET.get('date_to', '')

        date_from = parse_date(date_from_str) if date_from_str else None
        date_to   = parse_date(date_to_str)   if date_to_str   else None

        if export_type == 'login':
            qs = LoginAudit.objects.filter(user=target_user).order_by('-timestamp')
            if date_from:
                qs = qs.filter(timestamp__date__gte=date_from)
            if date_to:
                qs = qs.filter(timestamp__date__lte=date_to)
            records = list(qs[:500])  # hard cap for safety
        else:
            qs = AuditLog.objects.filter(performed_by=target_user).order_by('-timestamp')
            if date_from:
                qs = qs.filter(timestamp__date__gte=date_from)
            if date_to:
                qs = qs.filter(timestamp__date__lte=date_to)
            records = list(qs[:500])

        AuditLog.objects.create(
            action="ADMIN_USER_ACTIVITY_EXPORT",
            performed_by=request.user,
            details={
                "target_public_id": target_user.id,
                "export_type": export_type,
                "date_from": date_from_str,
                "date_to": date_to_str,
                "record_count": len(records),
            }
        )

        
        return drender(request, 'admin_portal/user_activity_export.html', {
            'target_user': target_user,
            'records': records,
            'export_type': export_type,
            'date_from': date_from,
            'date_to': date_to,
            'generated_at': tz.now(),
            'generated_by': request.user,
            'total_records': len(records),
        })


class AdminUserHardDeleteView(SuperAdminRequiredMixin, View):
    """Permanently deletes a user and all their data. Requires confirmation token."""
    def post(self, request, public_id):
        target_user = get_object_or_404(User, public_id=self.kwargs['public_id'])
        if target_user == request.user:
            messages.error(request, "You cannot delete your own superuser account.")
            return redirect('admin_portal:users')

        confirm = request.POST.get('confirm_delete', '').strip()
        if confirm != target_user.username:
            messages.error(request, "Confirmation username did not match. Hard delete cancelled.")
            return redirect('admin_portal:user_detail', public_id=public_id)

        username = target_user.username
        AuditLog.objects.create(
            action="ADMIN_USER_HARD_DELETE",
            performed_by=request.user,
            details={"deleted_public_id": target_user.id, "deleted_username": username}
        )
        target_user.delete()
        messages.success(request, f"User '{username}' and all associated data permanently deleted.")
        return redirect('admin_portal:users')


class AdminUserBlockView(SuperAdminRequiredMixin, View):
    """Hard-blocks or unblocks a user account.

    Blocking sets is_active=False which prevents Django from authenticating
    the user entirely — they cannot log in at all.
    This is the strongest action short of hard deletion.
    """

    def post(self, request, public_id):
        target_user = get_object_or_404(User, public_id=public_id)

        if target_user == request.user:
            messages.error(request, "You cannot block your own account.")
            return redirect('admin_portal:user_detail', public_id=public_id)

        action = request.POST.get('action', 'block')

        if action == 'block':
            target_user.is_active = False
            target_user.is_staff = False
            target_user.save(update_fields=['is_active', 'is_staff'])

            email_heading = "Your Account Has Been Blocked"
            email_body = (
                f"<p>Your VerifyNG account (<strong>{target_user.email}</strong>) "
                f"has been <strong>blocked</strong> by an administrator.</p>"
                f"<p>You will no longer be able to sign in to the platform.</p>"
                f"<p>If you believe this is an error or wish to appeal, "
                f"please contact our support team directly.</p>"
            )
            audit_action = "ADMIN_USER_BLOCKED"
            action_label = "blocked"

        elif action == 'unblock':
            target_user.is_active = True
            target_user.save(update_fields=['is_active'])

            email_heading = "Your Account Has Been Unblocked"
            email_body = (
                f"<p>Your VerifyNG account (<strong>{target_user.email}</strong>) "
                f"has been <strong>unblocked</strong> by an administrator.</p>"
                f"<p>You can now sign in and use the platform again.</p>"
            )
            audit_action = "ADMIN_USER_UNBLOCKED"
            action_label = "unblocked"

        else:
            messages.error(request, "Invalid action.")
            return redirect('admin_portal:user_detail', public_id=public_id)

        # Send email notification to user
        try:
            html_body, text_body = render_email('generic_notification', {
                'user_name': target_user.get_full_name() or target_user.username,
                'heading': email_heading,
                'body_html': email_body,
                'subject': email_heading,
            })
            send_broadcast_email_task.delay(
                to_email=target_user.email,
                subject=email_heading,
                html_body=html_body,
                text_body=text_body,
            )
        except Exception as exc:
            logger.warning("Failed to send block email to %s: %s", target_user.email, exc)

        AuditLog.objects.create(
            action=audit_action,
            performed_by=request.user,
            details={
                "target_public_id": str(target_user.public_id),
                "target_username": target_user.username,
            }
        )
        messages.success(request, f"User '{target_user.username}' has been {action_label}.")
        return redirect('admin_portal:user_detail', public_id=public_id)


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

        counts = {s[0]: FraudReport.objects.filter(state=s[0]).count() for s in FraudReport.STATES}
        per_page = int(self.request.GET.get('per_page', 15))
        if per_page not in (15, 25, 50, 100):
            per_page = 15
        paginator = Paginator(reports, per_page)
        ctx['page_obj'] = paginator.get_page(self.request.GET.get('page', 1))
        ctx['per_page'] = per_page
        ctx['per_page_options'] = [15, 25, 50, 100]
        ctx['counts'] = counts
        ctx['total_count'] = sum(counts.values())
        ctx['state_choices'] = [(key, label, counts.get(key, 0)) for key, label in FraudReport.STATES]
        ctx['selected_state'] = state_filter
        ctx['q'] = q
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

        disputes = Dispute.objects.select_related('report', 'disputant').order_by('-created_at')

        if status_filter:
            disputes = disputes.filter(status=status_filter)
        if q:
            disputes = disputes.filter(report__reference_number__icontains=q)

        per_page = int(self.request.GET.get('per_page', 15))
        if per_page not in (15, 25, 50, 100):
            per_page = 15
        paginator = Paginator(disputes, per_page)
        ctx['page_obj'] = paginator.get_page(self.request.GET.get('page', 1))
        ctx['per_page'] = per_page
        ctx['per_page_options'] = [15, 25, 50, 100]
        ctx['status_choices'] = Dispute.DISPUTE_STATES
        ctx['selected_status'] = status_filter
        ctx['q'] = q
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


class AdminDisputeDetailView(SuperAdminRequiredMixin, TemplateView):
    """Full dispute detail — shows report content, disputant reason, and resolution form."""
    template_name = "admin_portal/dispute_detail.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['dispute'] = get_object_or_404(
            Dispute.objects.select_related('report', 'disputant', 'report__reporter', 'report__target_subject'),
            pk=self.kwargs['pk']
        )
        return ctx

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
            messages.error(request, "Invalid action.")
            return redirect('admin_portal:dispute_detail', pk=pk)

        dispute.resolution_notes = resolution_notes
        dispute.resolved_at = timezone.now()
        dispute.save()

        AuditLog.objects.create(
            action=f"ADMIN_DISPUTE_{action.upper()}",
            performed_by=request.user,
            details={"dispute_id": dispute.id, "report_ref": dispute.report.reference_number}
        )
        messages.success(request, f"Dispute {action}ed. Report is now '{dispute.report.state}'.")
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

        per_page = int(self.request.GET.get('per_page', 15))
        if per_page not in (15, 25, 50, 100):
            per_page = 15
        paginator = Paginator(qs, per_page)
        ctx['page_obj'] = paginator.get_page(self.request.GET.get('page', 1))
        ctx['per_page'] = per_page
        ctx['per_page_options'] = [15, 25, 50, 100]
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

        per_page = int(self.request.GET.get('per_page', 15))
        if per_page not in (15, 25, 50, 100):
            per_page = 15

        if EmployerProfile:
            qs = EmployerProfile.objects.select_related('user').order_by('-created_at')
            if q:
                qs = qs.filter(company_name__icontains=q) | qs.filter(user__email__icontains=q)
            if verified_filter == 'yes':
                qs = qs.filter(is_verified=True)
            elif verified_filter == 'no':
                qs = qs.filter(is_verified=False)
            paginator = Paginator(qs, per_page)
            ctx['page_obj'] = paginator.get_page(self.request.GET.get('page', 1))
        else:
            ctx['page_obj'] = []
        ctx['per_page'] = per_page
        ctx['per_page_options'] = [15, 25, 50, 100]
        ctx['q'] = q
        ctx['verified_filter'] = verified_filter
        return ctx


class AdminEmployerDetailView(SuperAdminRequiredMixin, TemplateView):
    """Detail view for a single employer profile."""
    template_name = 'admin_portal/employer_detail.html'

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        profile = get_object_or_404(EmployerProfile, pk=self.kwargs['pk'])

        # Team members (no pagination — usually small number)
        team_members = TeamMember.objects.select_related('user').filter(
            employer=profile
        ).order_by('team_role', 'user__username')

        # Login history — paginated
        login_qs = LoginAudit.objects.filter(user=profile.user).order_by('-timestamp')
        ctx['login_history'] = Paginator(login_qs, 15).get_page(
            self.request.GET.get('login_page', 1)
        )

        # System activity — paginated
        activity_qs = AuditLog.objects.filter(performed_by=profile.user).order_by('-timestamp')
        ctx['user_activity'] = Paginator(activity_qs, 15).get_page(
            self.request.GET.get('activity_page', 1)
        )

        # Bulk upload history — paginated
        from employer.models import BulkCheckUpload
        bulk_qs = BulkCheckUpload.objects.filter(employer=profile).order_by('-created_at')
        ctx['bulk_uploads'] = Paginator(bulk_qs, 10).get_page(
            self.request.GET.get('bulk_page', 1)
        )

        ctx['profile'] = profile
        ctx['team_members'] = team_members
        ctx['active_tab'] = self.request.GET.get('tab', 'login')
        return ctx


class AdminEmployerActivityExportView(SuperAdminRequiredMixin, View):
    """Printable activity export for an employer account."""
    def get(self, request, pk):
        from django.utils.dateparse import parse_date
        from django.utils import timezone as tz

        profile = get_object_or_404(EmployerProfile, pk=pk)
        export_type = request.GET.get('type', 'login')
        date_from = parse_date(request.GET.get('date_from', '') or '')
        date_to   = parse_date(request.GET.get('date_to', '')   or '')

        if export_type == 'login':
            qs = LoginAudit.objects.filter(user=profile.user).order_by('-timestamp')
        else:
            qs = AuditLog.objects.filter(performed_by=profile.user).order_by('-timestamp')

        if date_from:
            qs = qs.filter(timestamp__date__gte=date_from)
        if date_to:
            qs = qs.filter(timestamp__date__lte=date_to)
        records = list(qs[:500])

        AuditLog.objects.create(
            action="ADMIN_EMPLOYER_ACTIVITY_EXPORT",
            performed_by=request.user,
            details={"employer_profile_id": profile.id, "company": profile.company_name,
                     "export_type": export_type, "record_count": len(records)}
        )
        return drender(request, 'admin_portal/user_activity_export.html', {
            'target_user': profile.user,
            'records': records,
            'export_type': export_type,
            'date_from': date_from,
            'date_to': date_to,
            'generated_at': tz.now(),
            'generated_by': request.user,
            'total_records': len(records),
        })
    

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
        elif action == 'reinstate':
            profile.user.is_active = True
            profile.user.save(update_fields=['is_active'])
            msg = f"Employer account '{profile.company_name}' reinstated."
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

        per_page = int(self.request.GET.get('per_page', 15))
        if per_page not in (15, 25, 50, 100):
            per_page = 15

        if Subscription:
            qs = Subscription.objects.select_related('user', 'plan').order_by('-created_at')
            if status_filter:
                qs = qs.filter(status=status_filter)
            if q:
                qs = qs.filter(user__email__icontains=q) | qs.filter(user__username__icontains=q)
            paginator = Paginator(qs, per_page)
            ctx['page_obj'] = paginator.get_page(self.request.GET.get('page', 1))
            ctx['status_choices'] = Subscription.STATUS_CHOICES
        else:
            ctx['page_obj'] = []
            ctx['status_choices'] = []
        ctx['per_page'] = per_page
        ctx['per_page_options'] = [15, 25, 50, 100]
        ctx['selected_status'] = status_filter
        ctx['q'] = q
        return ctx

class AdminSubscriptionActionView(SuperAdminRequiredMixin, View):
    """POST: cancel or reactivate a subscription."""
    def post(self, request, pk):
        sub = get_object_or_404(Subscription, pk=pk)
        action = request.POST.get('action', 'cancel')
        reason = request.POST.get('reason', '').strip()

        if action == 'cancel':
            sub.status = 'cancelled'
            sub.save(update_fields=['status'])
            AuditLog.objects.create(
                action="ADMIN_SUBSCRIPTION_CANCEL",
                performed_by=request.user,
                details={"subscription_id": sub.id, "user": sub.user.username, "reason": reason or "Admin cancellation"}
            )
            messages.success(request, f"Subscription for '{sub.user.username}' cancelled.")
        elif action == 'reactivate':
            sub.status = 'active'
            sub.save(update_fields=['status'])
            AuditLog.objects.create(
                action="ADMIN_SUBSCRIPTION_REACTIVATE",
                performed_by=request.user,
                details={"subscription_id": sub.id, "user": sub.user.username}
            )
            messages.success(request, f"Subscription for '{sub.user.username}' reactivated.")
        else:
            messages.error(request, "Invalid action.")
        return redirect('admin_portal:subscriptions')
    

class AdminPlansView(SuperAdminRequiredMixin, TemplateView):
    """List all subscription plans with management actions."""
    template_name = "admin_portal/plans.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        if Plan:
            ctx['plans'] = Plan.objects.prefetch_related('features').order_by('display_order', 'price_kobo')
        else:
            ctx['plans'] = []
        return ctx


class AdminPlanCreateEditView(SuperAdminRequiredMixin, View):
    """Create or edit a Plan and its bullet-point features."""
    template_name = "admin_portal/plan_form.html"

    def _get_plan(self, pk):
        if pk:
            return get_object_or_404(Plan, pk=pk)
        return None

    def get(self, request, pk=None):
        plan = self._get_plan(pk)
        
        features_json = _json.dumps([
            {'text': f.feature_text, 'is_included': f.is_included}
            for f in (plan.features.all() if plan else [])
        ])
        return render(request, self.template_name, {
            'plan': plan,
            'interval_choices': Plan.INTERVAL_CHOICES if Plan else [],
            'features_json': features_json,
        })

    def post(self, request, pk=None):
        plan = self._get_plan(pk)
        is_new = plan is None

        name         = request.POST.get('name', '').strip()
        description  = request.POST.get('description', '').strip()
        price_naira  = request.POST.get('price_naira', '0').strip()
        interval     = request.POST.get('interval', 'monthly').strip()
        check_limit  = request.POST.get('check_limit', '10').strip()
        paystack_code= request.POST.get('paystack_plan_code', '').strip()
        is_featured  = request.POST.get('is_featured') == 'on'
        is_active    = request.POST.get('is_active') == 'on'
        display_order= request.POST.get('display_order', '0').strip()

        if not name:
            messages.error(request, "Plan name is required.")
            return render(request, self.template_name, {
                'plan': plan,
                'interval_choices': Plan.INTERVAL_CHOICES,
            })

        try:
            price_kobo = int(float(price_naira) * 100)
        except (ValueError, TypeError):
            price_kobo = 0

        try:
            check_limit_int = int(check_limit)
        except (ValueError, TypeError):
            check_limit_int = 10

        try:
            display_order_int = int(display_order)
        except (ValueError, TypeError):
            display_order_int = 0

        if is_new:
            slug = slugify(name)
            # Ensure unique slug
            base_slug = slug
            counter = 1
            while Plan.objects.filter(slug=slug).exists():
                slug = f"{base_slug}-{counter}"
                counter += 1
            plan = Plan(slug=slug)

        plan.name          = name
        plan.description   = description
        plan.price_kobo    = price_kobo
        plan.interval      = interval
        plan.check_limit   = check_limit_int
        plan.paystack_plan_code = paystack_code
        plan.is_featured   = is_featured
        plan.is_active     = is_active
        plan.display_order = display_order_int
        plan.save()

        # Replace features: delete all, re-create from POST
        
        plan.features.all().delete()
        feature_texts = request.POST.getlist('feature_text')
        feature_included = request.POST.getlist('feature_included')
        for i, text in enumerate(feature_texts):
            text = text.strip()
            if text:
                included = str(i) in feature_included
                PlanFeature.objects.create(
                    plan=plan,
                    feature_text=text,
                    is_included=included,
                    display_order=i,
                )

        log_admin_action(
            action='PLAN_CREATED' if is_new else 'PLAN_UPDATED',
            action_type='ADMIN',
            performed_by=request.user,
            request=request,
            details={'plan_id': plan.pk, 'plan_name': plan.name},
        )
        messages.success(request, f"Plan '{ plan.name }' {'created' if is_new else 'updated'} successfully.")
        return redirect('admin_portal:plans')


class AdminCreditSubscriptionView(SuperAdminRequiredMixin, View):
    """
    POST: Manually credit (assign) a subscription plan to a user.
    Called from the user detail quick-actions panel.
    """
    def post(self, request, public_id):
        from django.utils import timezone as tz
        user = get_object_or_404(User, public_id=public_id)
        plan_id = request.POST.get('plan_id', '').strip()
        duration_days = request.POST.get('duration_days', '30').strip()
        reason = request.POST.get('reason', 'Admin credit').strip()

        if not plan_id:
            messages.error(request, "Please select a plan.")
            return redirect('admin_portal:user_detail', public_id=public_id)

        plan = get_object_or_404(Plan, pk=plan_id)

        try:
            days = int(duration_days)
            if days < 1:
                days = 30
        except (ValueError, TypeError):
            days = 30

        now = tz.now()

        # Block assigning the same plan if already active
        existing_active = Subscription.objects.filter(
            user=user, plan=plan, status='active'
        ).first()
        if existing_active:
            messages.error(
                request,
                f"'{user.username}' already has an active '{plan.name}' subscription "
                f"(expires {existing_active.current_period_end.strftime('%d %b %Y')}). "
                f"Cancel it first or choose a different plan."
            )
            return redirect('admin_portal:user_detail', public_id=public_id)

        # Cancel any other active subscription before assigning new one
        Subscription.objects.filter(user=user, status='active').update(
            status='cancelled',
            cancel_at_period_end=False,
        )

        sub = Subscription.objects.create(
            user=user,
            plan=plan,
            status='active',
            current_period_start=now,
            current_period_end=now + tz.timedelta(days=days),
        )

        log_admin_action(
            action='SUBSCRIPTION_CREDITED',
            action_type='ADMIN',
            performed_by=request.user,
            target_user=user,
            request=request,
            details={
                'plan': plan.name,
                'duration_days': days,
                'subscription_id': str(sub.pk),
                'reason': reason,
            },
        )
        messages.success(
            request,
            f"Plan '{plan.name}' credited to {user.username} for {days} days."
        )
        return redirect('admin_portal:user_detail', public_id=public_id)
    

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
                # Subscription & revenue data
        if Subscription:
            from django.db.models import Sum
            active_subs = Subscription.objects.filter(status='active')
            ctx['active_subscriptions'] = active_subs.count()
        else:
            ctx['active_subscriptions'] = 0

        if Transaction:
            from django.db.models import Sum
            ctx['revenue_30d_kobo'] = Transaction.objects.filter(
                status='success',
                created_at__gte=thirty_days_ago
            ).aggregate(total=Sum('amount_kobo'))['total'] or 0
            ctx['revenue_alltime_kobo'] = Transaction.objects.filter(
                status='success'
            ).aggregate(total=Sum('amount_kobo'))['total'] or 0
            ctx['transactions_30d'] = Transaction.objects.filter(
                status='success',
                created_at__gte=thirty_days_ago
            ).count()
        else:
            ctx['revenue_30d_kobo'] = 0
            ctx['revenue_alltime_kobo'] = 0
            ctx['transactions_30d'] = 0

        return ctx


class AdminNotificationsView(SuperAdminRequiredMixin, TemplateView):
    """Platform-wide admin notification digest — pending actions requiring attention."""
    template_name = "admin_portal/notifications.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        from django.utils import timezone as tz

        now = tz.now()

        # Pending / in-review reports
        ctx['pending_reports'] = FraudReport.objects.filter(
            state__in=['submitted', 'under_review']
        ).order_by('-created_at')[:20]
        ctx['pending_reports_count'] = FraudReport.objects.filter(
            state__in=['submitted', 'under_review']
        ).count()

        # Open disputes
        ctx['open_disputes'] = Dispute.objects.filter(
            status__in=['opened', 'under_review']
        ).select_related('report', 'disputant').order_by('-created_at')[:20]
        ctx['open_disputes_count'] = Dispute.objects.filter(
            status__in=['opened', 'under_review']
        ).count()

        # Certificates expiring within 30 days
        from verification.models import VerificationCertificate
        thirty_days = now + timedelta(days=30)
        ctx['expiring_certs'] = VerificationCertificate.objects.filter(
            status='active',
            expires_at__lte=thirty_days,
            expires_at__gt=now
        ).select_related('holder').order_by('expires_at')[:20]
        ctx['expiring_certs_count'] = VerificationCertificate.objects.filter(
            status='active',
            expires_at__lte=thirty_days,
            expires_at__gt=now
        ).count()

        # Unverified employer profiles
        if EmployerProfile:
            ctx['unverified_employers'] = EmployerProfile.objects.filter(
                is_verified=False, user__is_active=True
            ).select_related('user').order_by('-created_at')[:20]
            ctx['unverified_employers_count'] = EmployerProfile.objects.filter(
                is_verified=False, user__is_active=True
            ).count()
        else:
            ctx['unverified_employers'] = []
            ctx['unverified_employers_count'] = 0

        # Failed transactions (last 7 days)
        from payments.models import Transaction
        seven_days_ago = now - timedelta(days=7)
        ctx['failed_transactions'] = Transaction.objects.filter(
            status='failed',
            created_at__gte=seven_days_ago
        ).select_related('user').order_by('-created_at')[:20]
        ctx['failed_transactions_count'] = Transaction.objects.filter(
            status='failed',
            created_at__gte=seven_days_ago
        ).count()

        ctx['total_alerts'] = (
            ctx['pending_reports_count'] +
            ctx['open_disputes_count'] +
            ctx['expiring_certs_count'] +
            ctx['unverified_employers_count'] +
            ctx['failed_transactions_count']
        )
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

        ctx['action_types'] = AuditLog.objects.values_list('action', flat=True).distinct().order_by('action')[:50]

        per_page = int(self.request.GET.get('per_page', 15))
        if per_page not in (15, 25, 50, 100):
            per_page = 15
        paginator = Paginator(logs, per_page)
        ctx['page_obj'] = paginator.get_page(self.request.GET.get('page', 1))
        ctx['per_page'] = per_page
        ctx['per_page_options'] = [15, 25, 50, 100]
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

        ctx['total_logins'] = LoginAudit.objects.count()
        ctx['failed_logins'] = LoginAudit.objects.filter(status='failed').count()
        ctx['blocked_logins'] = LoginAudit.objects.filter(status='blocked').count()
        ctx['success_logins'] = LoginAudit.objects.filter(status='success').count()

        per_page = int(self.request.GET.get('per_page', 15))
        if per_page not in (15, 25, 50, 100):
            per_page = 15
        paginator = Paginator(logs, per_page)
        ctx['page_obj'] = paginator.get_page(self.request.GET.get('page', 1))
        ctx['per_page'] = per_page
        ctx['per_page_options'] = [15, 25, 50, 100]
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

        # Per-service kill switches
        config.service_check_suspended = request.POST.get('service_check_suspended') == 'on'
        config.service_report_suspended = request.POST.get('service_report_suspended') == 'on'
        config.service_verify_suspended = request.POST.get('service_verify_suspended') == 'on'
        config.service_employment_suspended = request.POST.get('service_employment_suspended') == 'on'
        config.service_suspension_message = request.POST.get('service_suspension_message', config.service_suspension_message).strip()

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


# ─────────────────────────────────────────────────────────────────────────────
# Admin: Create New User
# ─────────────────────────────────────────────────────────────────────────────

class AdminCreateUserView(LoginRequiredMixin, UserPassesTestMixin, View):
    """
    Admin can register any new user directly from the portal.
    Assigns role, sets staff/superuser flags, sends welcome email.
    """
    template_name = 'admin_portal/create_user.html'

    def test_func(self):
        return is_superadmin(self.request.user)

    def get(self, request):
        return render(request, self.template_name, {
            'role_choices': User.ROLE_CHOICES,
        })

    def post(self, request):
        first_name  = request.POST.get('first_name', '').strip()
        last_name   = request.POST.get('last_name', '').strip()
        username    = request.POST.get('username', '').strip()
        email       = request.POST.get('email', '').strip().lower()
        role        = request.POST.get('role', 'individual')
        password    = request.POST.get('password', '').strip()
        is_staff    = request.POST.get('is_staff') == 'on'
        is_superuser = request.POST.get('is_superuser') == 'on'
        send_welcome = request.POST.get('send_welcome') == 'on'

        errors = []

        if not username:
            errors.append('Username is required.')
        if not email:
            errors.append('Email is required.')
        if not password or len(password) < 8:
            errors.append('Password must be at least 8 characters.')
        if User.objects.filter(username=username).exists():
            errors.append(f'Username "{username}" is already taken.')
        if User.objects.filter(email=email).exists():
            errors.append(f'Email "{email}" is already registered.')
        if role not in dict(User.ROLE_CHOICES):
            errors.append('Invalid role selected.')

        if errors:
            for e in errors:
                messages.error(request, e)
            return render(request, self.template_name, {
                'role_choices': User.ROLE_CHOICES,
                'form_data': request.POST,
            })

        with db_transaction.atomic():
            user = User.objects.create_user(
                username=username,
                email=email,
                password=password,
                first_name=first_name,
                last_name=last_name,
                role=role,
                is_staff=is_staff,
                is_superuser=is_superuser,
                is_active=True,
            )

            log_admin_action(
                action='USER_CREATED_BY_ADMIN',
                action_type='USER_MGMT',
                performed_by=request.user,
                target_user=user,
                request=request,
                details={
                    'username': username,
                    'email': email,
                    'role': role,
                    'is_staff': is_staff,
                    'is_superuser': is_superuser,
                },
            )

        if send_welcome:
            try:
                transaction.on_commit(lambda: send_email_notification_task.delay(
                    recipient_email=email,
                    subject='Welcome to VerifyNG',
                    template_name='emails/welcome.html',
                    context={
                        'user': {'username': username, 'first_name': first_name or username},
                        'login_url': request.build_absolute_uri('/accounts/login/'),
                        'temp_password': password,
                    },
                ))
            except Exception:
                pass  # Welcome email failure must not block user creation

        messages.success(
            request,
            f'User "{username}" created successfully with role "{role}".'
        )
        return redirect('admin_portal:users')


# ─────────────────────────────────────────────────────────────────────────────
# Admin: Toggle Per-User Service Access Restriction
# ─────────────────────────────────────────────────────────────────────────────

class AdminUserServiceAccessView(LoginRequiredMixin, UserPassesTestMixin, View):
    """
    Toggle a user's access to a specific platform service.
    POST with: service (str), action ('restrict' | 'allow'), reason (str)
    Returns JSON for Alpine.js to update the toggle UI.
    """

    def test_func(self):
        return is_superadmin(self.request.user)

    def post(self, request, public_id):
        target_user = get_object_or_404(User, public_id=public_id)
        service  = request.POST.get('service', '').strip()
        action   = request.POST.get('action', '').strip()   # 'restrict' or 'allow'
        reason   = request.POST.get('reason', '').strip()

        valid_services = [s[0] for s in UserServiceAccess.SERVICE_CHOICES]
        if service not in valid_services:
            return JsonResponse({'ok': False, 'error': 'Invalid service.'}, status=400)
        if action not in ('restrict', 'allow'):
            return JsonResponse({'ok': False, 'error': 'Invalid action.'}, status=400)

        is_restricted = action == 'restrict'

        rule, _ = UserServiceAccess.objects.get_or_create(
            user=target_user,
            service=service,
            defaults={
                'is_restricted': False,
                'restricted_by': None,
                'restricted_at': None,
                'reason': '',
            },
        )
        rule.is_restricted  = is_restricted
        rule.restricted_by  = request.user if is_restricted else None
        rule.restricted_at  = tz.now() if is_restricted else None
        rule.reason         = reason if is_restricted else ''
        rule.save()

        log_admin_action(
            action='SERVICE_RESTRICTED' if is_restricted else 'SERVICE_UNRESTRICTED',
            action_type='USER_MGMT',
            performed_by=request.user,
            target_user=target_user,
            request=request,
            details={'service': service, 'reason': reason},
        )

        service_label = dict(UserServiceAccess.SERVICE_CHOICES).get(service, service)
        status_label  = 'restricted' if is_restricted else 'unrestricted'
        return JsonResponse({
            'ok': True,
            'is_restricted': is_restricted,
            'message': f'{service_label} {status_label} for {target_user.username}.',
        })



# ── Certificate Admin ──────────────────────────────────────────────────────────

class AdminCertificatesView(SuperAdminRequiredMixin, TemplateView):
    """List all VerificationCertificates with filtering and bulk status management."""
    template_name = "admin_portal/certificates.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        if not VerificationCertificate:
            ctx['certificates'] = []
            ctx['no_model'] = True
            return ctx

        qs = VerificationCertificate.objects.select_related('holder', 'subject').order_by('-created_at')

        # Filters
        status_filter = self.request.GET.get('status', '')
        level_filter = self.request.GET.get('level', '')
        q = self.request.GET.get('q', '').strip()

        if status_filter:
            qs = qs.filter(status=status_filter)
        if level_filter:
            qs = qs.filter(check_level=level_filter)
        if q:
            qs = qs.filter(
                Q(certificate_id__icontains=q) |
                Q(holder__username__icontains=q) |
                Q(holder__email__icontains=q)
            )

        paginator = Paginator(qs, 30)
        page = self.request.GET.get('page', 1)
        ctx['certificates'] = paginator.get_page(page)
        ctx['status_filter'] = status_filter
        ctx['level_filter'] = level_filter
        ctx['q'] = q
        ctx['status_choices'] = VerificationCertificate.STATUS_CHOICES
        ctx['level_choices'] = VerificationCertificate.CHECK_LEVEL_CHOICES
        ctx['total'] = qs.count()
        ctx['now'] = timezone.now()
        return ctx


class AdminCertificateActionView(SuperAdminRequiredMixin, View):
    """Activate, suspend, or revoke a certificate."""

    def post(self, request, pk):
        if not VerificationCertificate:
            return JsonResponse({'ok': False, 'error': 'Certificate model not available.'}, status=400)

        cert = get_object_or_404(VerificationCertificate, pk=pk)
        action = request.POST.get('action', '').strip()
        reason = request.POST.get('reason', '').strip()

        now = timezone.now()

        if action == 'activate':
            cert.status = 'active'
            cert.issued_at = cert.issued_at or now
            cert.revoked_at = None
            cert.suspended_at = None
            cert.revocation_reason = ''
            cert.suspension_reason = ''
        elif action == 'suspend':
            cert.status = 'suspended'
            cert.suspended_at = now
            cert.suspension_reason = reason
        elif action == 'revoke':
            cert.status = 'revoked'
            cert.revoked_at = now
            cert.revocation_reason = reason
        else:
            return JsonResponse({'ok': False, 'error': 'Unknown action.'}, status=400)

        cert.save()

        log_admin_action(
            action=f'CERTIFICATE_{action.upper()}',
            action_type='CERTIFICATE_MGMT',
            performed_by=request.user,
            request=request,
            details={'certificate_id': cert.certificate_id, 'reason': reason},
        )

        return JsonResponse({
            'ok': True,
            'status': cert.status,
            'certificate_id': cert.certificate_id,
            'message': f'Certificate {cert.certificate_id} {action}d successfully.',
        })






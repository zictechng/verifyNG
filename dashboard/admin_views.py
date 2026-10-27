
import json
import json as _json
import logging
from datetime import timedelta, datetime
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
from verification.models import VerificationRequest, VerificationResult
from core.models import SiteConfiguration
from identities.models import Identifier, SubjectEntity
from core.permissions import is_superadmin
from core.tasks import send_email_notification_task
from payments.models import Plan as PlanModel
from dateutil.relativedelta import relativedelta
from reports.storage_services import get_storage_service
import mimetypes
import urllib.request
from django.http import Http404, HttpResponse                   
from django.db.models import Q
from django.utils.dateparse import parse_date
from django.utils import timezone as tz
from core.email_utils import render_email
from notifications.tasks import send_broadcast_email_task
from django.http import HttpResponse, JsonResponse
from django.utils import timezone as tz
from django.contrib.auth.models import Group
from payments.models import Plan, PlatformConfiguration

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

from payments.models import Transaction as TxnModel
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_RIGHT, TA_CENTER, TA_LEFT
import io
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.units import mm
from reportlab.platypus import (
    SimpleDocTemplate, Table, TableStyle, Paragraph,
    Spacer, HRFlowable, KeepTogether, Flowable
)

import csv as csv_mod
from payments.models import Transaction
from django.db.models import Sum, Count, Avg
from django.core.paginator import Paginator
from payments.models import Transaction, Subscription

from employer.models import BulkCheckUpload

from django.conf import settings as django_settings
import os
from users.models import UserServiceAccess

from reportlab.platypus import (
    HRFlowable, KeepTogether, Paragraph,
    SimpleDocTemplate, Spacer, Table, TableStyle,
)
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.lib.units import mm

# Import models needed for extended admin
try:
    from reports.models import Dispute
except ImportError:
    Dispute = None

try:
    from verification.models import VerificationRequest, VerificationResult, VerificationCertificate

except ImportError:
    VerificationRequest = None
    VerificationCertificate = None

try:
    from employer.models import EmployerProfile, TeamMember
except ImportError:
    EmployerProfile = None

try:
    from payments.models import Subscription, Plan, SiteSettings, PlatformConfiguration, FreeUsageQuota
    from payments.services import get_active_subscription
except ImportError:
    Subscription = None
    Plan = None
    SiteSettings = None
    PlatformConfiguration = None
    FreeUsageQuota = None
    get_active_subscription = None

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

        # Auto-create EmployerProfile when role is set to any organization entity
        if new_role in ('employer', 'agency', 'business') and EmployerProfile is not None:
            EmployerProfile.objects.get_or_create(
                user=target_user,
                defaults={
                    'company_name': target_user.get_full_name() or target_user.username,
                }
            )

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


class AdminUserIdentityDocumentView(SuperAdminRequiredMixin, View):
    """
    Secure document stream proxy for compliance officers to view a user's uploaded government ID inline.
    """
    def get(self, request, public_id):
        target_user = get_object_or_404(User, public_id=public_id)
        if not target_user.has_id_document:
            raise Http404("No identity document uploaded for this user.")

        try:
            doc_file = target_user.id_document.open('rb')
        except Exception:
            raise Http404("Could not access the identity document.")

        ext = target_user.id_document.name.split('.')[-1].lower() if '.' in target_user.id_document.name else 'pdf'
        content_type, _ = mimetypes.guess_type(target_user.id_document.name)
        if not content_type:
            content_type = 'application/pdf' if ext == 'pdf' else 'image/jpeg'

        as_download = request.GET.get('download') == '1'
        disposition = 'attachment' if as_download else 'inline'
        safe_name = f"ID_{slugify(target_user.username) or 'proof'}.{ext}"

        response = HttpResponse(doc_file.read(), content_type=content_type)
        response['Content-Disposition'] = f'{disposition}; filename="{safe_name}"'
        response['X-Frame-Options'] = 'SAMEORIGIN'
        doc_file.close()

        AuditLog.objects.create(
            action="ADMIN_VIEW_USER_IDENTITY_DOCUMENT",
            performed_by=request.user,
            details={"target_user_id": target_user.id, "target_username": target_user.username}
        )
        return response

class AdminUserDetailView(SuperAdminRequiredMixin, TemplateView):
    """Full user profile: all fields, login history, reports, verifications, subscriptions."""
    template_name = "admin_portal/user_detail.html"
    def post(self, request, public_id):
        target_user = get_object_or_404(User, public_id=public_id)
        action = request.POST.get('action')
        if action == 'update_billing_exempt':
            target_user.is_billing_exempt = request.POST.get('is_billing_exempt') == 'on'
            target_user.exempt_services = request.POST.getlist('exempt_services')
            target_user.billing_exempt_notes = request.POST.get('billing_exempt_notes', '').strip()
            target_user.save(update_fields=['is_billing_exempt', 'exempt_services', 'billing_exempt_notes'])
            count = len(target_user.exempt_services)
            AuditLog.objects.create(
                action="ADMIN_USER_BILLING_EXEMPT_UPDATE",
                performed_by=request.user,
                details={
                    "target_username": target_user.username,
                    "is_billing_exempt": target_user.is_billing_exempt,
                    "exempt_services": target_user.exempt_services,
                    "notes": target_user.billing_exempt_notes,
                }
            )
            messages.success(request, f"Service entitlements updated for '{target_user.username}' ({count} service(s) complimentary).")
            return redirect('admin_portal:user_detail', public_id=public_id)
        
        elif action == 'verify_identity':
            target_user.identity_verified = True
            target_user.id_verification_status = 'verified'
            target_user.id_verified_at = timezone.now()
            target_user.id_rejection_reason = ''
            target_user.save(update_fields=['identity_verified', 'id_verification_status', 'id_verified_at', 'id_rejection_reason'])
            AuditLog.objects.create(
                action="ADMIN_USER_IDENTITY_VERIFIED",
                performed_by=request.user,
                details={
                    "target_user_id": target_user.id,
                    "target_username": target_user.username,
                    "id_type": target_user.id_type,
                    "id_number": target_user.masked_id_number,
                }
            )
            messages.success(request, f"Government identity verified for '{target_user.get_full_name() or target_user.username}'.")
            return redirect('admin_portal:user_detail', public_id=public_id)

        elif action == 'reject_identity':
            target_user.identity_verified = False
            target_user.id_verification_status = 'rejected'
            reason = request.POST.get('rejection_reason', '').strip()
            target_user.id_rejection_reason = reason if reason else 'Document could not be authenticated against registry standards.'
            target_user.save(update_fields=['identity_verified', 'id_verification_status', 'id_rejection_reason'])
            AuditLog.objects.create(
                action="ADMIN_USER_IDENTITY_REJECTED",
                performed_by=request.user,
                details={
                    "target_user_id": target_user.id,
                    "target_username": target_user.username,
                    "reason": target_user.id_rejection_reason,
                }
            )
            messages.success(request, f"Identity proof declined for '{target_user.username}'.")
            return redirect('admin_portal:user_detail', public_id=public_id)

        elif action == 'revoke_identity':
            target_user.identity_verified = False
            target_user.id_verification_status = 'unverified'
            target_user.save(update_fields=['identity_verified', 'id_verification_status'])
            AuditLog.objects.create(
                action="ADMIN_USER_IDENTITY_REVOKED",
                performed_by=request.user,
                details={
                    "target_user_id": target_user.id,
                    "target_username": target_user.username,
                }
            )
            messages.success(request, f"Identity verification badge revoked for '{target_user.username}'.")
            return redirect('admin_portal:user_detail', public_id=public_id)

        messages.error(request, "Invalid action.")
        return redirect('admin_portal:user_detail', public_id=public_id)

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
            active_sub = get_active_subscription(target_user)
            ctx['active_subscription'] = active_sub
            ctx['user_active_plan_id'] = active_sub.plan.pk if active_sub else None
        else:
            ctx['available_plans'] = []
            ctx['active_subscription'] = None
            ctx['user_active_plan_id'] = None
        ctx['free_quota'] = FreeUsageQuota.for_user(target_user)
        ctx['site_settings'] = SiteSettings.get()
        from payments.services import get_user_prepaid_balance
        from payments.models import Transaction
        ctx['user_prepaid_balance'] = get_user_prepaid_balance(target_user)
        ctx['user_transactions'] = Transaction.objects.filter(user=target_user).order_by('-created_at')[:10]
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
        lookup = {'public_id': self.kwargs['public_id']} if 'public_id' in self.kwargs else {'pk': self.kwargs['pk']}
        report = get_object_or_404(
            FraudReport.objects.select_related('reporter', 'target_subject'),
            **lookup
        )
        ctx['report'] = report
        ctx['evidence_list'] = report.evidence_files.all()
        ctx['disputes'] = report.disputes.select_related('disputant').order_by('-created_at') if hasattr(report, 'disputes') else []
        ctx['complainant_rebuttal'] = report.complainant_rebuttal
        ctx['moderator_info_requests'] = report.moderator_info_requests
        from reports.forms import ModeratorInfoRequestForm
        ctx['info_request_form'] = ModeratorInfoRequestForm()
        ctx['audit_trail'] = report.audit_logs.all().order_by('-timestamp')[:30]
        ctx['state_choices'] = FraudReport.STATES
        return ctx


class AdminReportLegacyRedirectView(SuperAdminRequiredMixin, View):
    """Backward-compatible redirect from integer PK to UUID-based report detail."""
    def get(self, request, pk):
        report = get_object_or_404(FraudReport, pk=pk)
        return redirect('admin_portal:report_detail', public_id=report.public_id)


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

    def post(self, request, public_id=None, pk=None):
        lookup = {'public_id': public_id} if public_id else {'pk': pk}
        report = get_object_or_404(FraudReport, **lookup)
        new_state = request.POST.get('new_state', '').strip()
        moderation_notes = request.POST.get('moderation_notes', '').strip()

        allowed = self.VALID_TRANSITIONS.get(report.state, [])
        if new_state not in allowed:
            messages.error(request, f"Cannot transition from '{report.state}' to '{new_state}'.")
            return redirect('admin_portal:report_detail', public_id=report.public_id)

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
        return redirect('admin_portal:report_detail', public_id=report.public_id)


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

class AdminDisputeLegacyRedirectView(SuperAdminRequiredMixin, View):
    """Backward-compatible redirect from integer PK to UUID-based dispute detail."""
    def get(self, request, pk):
        dispute = get_object_or_404(Dispute, pk=pk)
        return redirect('admin_portal:dispute_detail', public_id=dispute.public_id)


class AdminDisputeActionView(SuperAdminRequiredMixin, View):
    """POST: Accept (uphold) or Reject a dispute via the official service layer."""
    def post(self, request, public_id=None, pk=None):
        lookup = {'public_id': public_id} if public_id else {'pk': pk}
        dispute = get_object_or_404(Dispute.objects.select_related('report', 'disputant', 'report__reporter'), **lookup)
        action = request.POST.get('action', '')
        resolution_notes = request.POST.get('resolution_notes', '').strip()

        if action not in ('accept', 'reject'):
            messages.error(request, "Invalid dispute action.")
            return redirect('admin_portal:disputes')

        outcome = 'accepted' if action == 'accept' else 'rejected'
        from reports.services import resolve_dispute
        from core.rate_limiting import get_client_ip

        resolve_dispute(
            dispute=dispute,
            outcome=outcome,
            actor=request.user,
            resolution_notes=resolution_notes,
            ip_address=get_client_ip(request)
        )

        outcome_text = "accepted & upheld (report quarantined/restricted)" if outcome == 'accepted' else "rejected (report published)"
        messages.success(request, f"Dispute on {dispute.report.reference_number} has been {outcome_text}.")
        return redirect('admin_portal:disputes')


class AdminDisputeDetailView(SuperAdminRequiredMixin, TemplateView):
    """Full dispute detail — shows report content, disputant reason, evidence, rebuttal, and resolution form."""
    template_name = "admin_portal/dispute_detail.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        lookup = {'public_id': self.kwargs['public_id']} if 'public_id' in self.kwargs else {'pk': self.kwargs['pk']}
        dispute = get_object_or_404(
            Dispute.objects.select_related('report', 'disputant', 'report__reporter', 'report__target_subject'),
            **lookup
        )
        ctx['dispute'] = dispute
        ctx['evidence_list'] = dispute.report.evidence_files.all()
        ctx['complainant_rebuttal'] = dispute.report.complainant_rebuttal
        ctx['moderator_info_requests'] = dispute.report.moderator_info_requests
        return ctx

    def post(self, request, public_id=None, pk=None):
        lookup = {'public_id': public_id} if public_id else {'pk': pk}
        dispute = get_object_or_404(Dispute.objects.select_related('report', 'disputant', 'report__reporter'), **lookup)
        action = request.POST.get('action', '')
        resolution_notes = request.POST.get('resolution_notes', '').strip()

        if action not in ('accept', 'reject'):
            messages.error(request, "Invalid action.")
            return redirect('admin_portal:dispute_detail', public_id=dispute.public_id)

        outcome = 'accepted' if action == 'accept' else 'rejected'
        from reports.services import resolve_dispute
        from core.rate_limiting import get_client_ip

        resolve_dispute(
            dispute=dispute,
            outcome=outcome,
            actor=request.user,
            resolution_notes=resolution_notes,
            ip_address=get_client_ip(request)
        )

        outcome_text = "upheld & accepted (report restricted from public view)" if outcome == 'accepted' else "rejected (allegation retained & published)"
        messages.success(request, f"Dispute resolution recorded: {outcome_text}.")
        return redirect('admin_portal:dispute_detail', public_id=dispute.public_id)

    
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
        if VerificationCertificate:
            ctx['pending_certificates_count'] = VerificationCertificate.objects.filter(status='pending').count()
        return ctx


def _dispatch_admin_verification_email(req, action, notes=None):
    requester_email = getattr(req.requester, 'email', None) if req.requester else None
    if not requester_email:
        return

    try:
        config = SiteConfiguration.get_solo()
        site_url = config.base_url.rstrip('/')
        site_name = config.site_name
    except Exception:
        site_url = "http://localhost:8000"
        site_name = "VerifyNG"

    user_name = req.requester.get_full_name() or req.requester.username
    subject_name = req.target_subject.name if req.target_subject else 'Target Subject'
    ref_id = req.reference_number
    scope_display = dict(VerificationRequest.VERIFICATION_TYPES).get(req.verification_type, req.verification_type)

    if action == 'complete':
        try:
            html_body, text_body = render_email('verification_complete', {
                'user_name': user_name,
                'reference_number': ref_id,
                'subject_name': subject_name,
                'scope_display': scope_display,
                'outcome_display': 'Verified Genuine',
                'outcome': 'verified',
                'summary': notes or 'Official verification confirmed and approved by administrator.',
                'completed_at': timezone.now().strftime('%d %B %Y, %I:%M %p'),
                'report_url': f"{site_url}/verification/{ref_id}/report/",
                'detail_url': f"{site_url}/verification/{ref_id}/",
            })
            email_subject = f"Verification Completed [{ref_id}]: Verified Genuine — {site_name}"
        except Exception:
            html_body = None
            email_subject = f"Verification Completed [{ref_id}]: Verified Genuine"
            text_body = (
                f"Hello {user_name},\n\n"
                f"Your verification request [{ref_id}] for '{subject_name}' has been completed.\n"
                f"Official Verdict: Verified Genuine\n\n"
                f"View report: {site_url}/verification/{ref_id}/report/\n\n"
                f"{site_name} Trust & Safety Team"
            )
        send_email_notification_task.delay(requester_email, email_subject, text_body, html_message=html_body)

    elif action == 'reject':
        reason_text = notes or "Supporting documentation could not be substantiated against primary records."
        try:
            html_body, text_body = render_email('verification_declined', {
                'user_name': user_name,
                'reference_number': ref_id,
                'subject_name': subject_name,
                'scope_display': scope_display,
                'reason': reason_text,
                'declined_at': timezone.now().strftime('%d %B %Y, %I:%M %p'),
                'detail_url': f"{site_url}/verification/{ref_id}/",
            })
            email_subject = f"Update on Verification Request [{ref_id}] — {site_name}"
        except Exception:
            html_body = None
            email_subject = f"Update on Verification Request [{ref_id}]"
            text_body = (
                f"Hello {user_name},\n\n"
                f"Your verification request [{ref_id}] for '{subject_name}' could not be completed.\n"
                f"Reason: {reason_text}\n\n"
                f"{site_name} Trust & Safety Team"
            )
        send_email_notification_task.delay(requester_email, email_subject, text_body, html_message=html_body)


class AdminVerificationLegacyRedirectView(SuperAdminRequiredMixin, View):
    """Backward-compatible redirect from integer PK to UUID-based verification detail."""
    def get(self, request, pk):
        req = get_object_or_404(VerificationRequest, pk=pk)
        return redirect('admin_portal:verification_detail', public_id=req.public_id)


class AdminVerificationActionView(SuperAdminRequiredMixin, View):
    """POST: complete or reject a verification request."""
    def post(self, request, public_id=None, pk=None):
        lookup = {'public_id': public_id} if public_id else {'pk': pk}
        req = get_object_or_404(VerificationRequest, **lookup)
        action = request.POST.get('action', '')
        notes = request.POST.get('notes', '').strip()

        if action == 'complete':
            req.status = 'completed'
            if not hasattr(req, 'result') or req.result is None:
                VerificationResult.objects.get_or_create(
                    request=req,
                    defaults={
                        'outcome': 'verified',
                        'summary': notes or 'Official verification confirmed and approved by administrator.',
                        'verified_by': request.user,
                        'verified_at': timezone.now(),
                        'details': {
                            'registry_status': 'verified',
                            'record_status': 'authentic',
                            'officer_advisory': 'Verified and approved by system administration.'
                        }
                    }
                )
        elif action == 'reject':
            req.status = 'rejected'
        elif action == 'in_progress':
            req.status = 'in_progress'
        else:
            messages.error(request, "Invalid action.")
            return redirect('admin_portal:verifications')

        req.notes = notes
        req.save(update_fields=['status', 'notes', 'updated_at'])

        if action in ('complete', 'reject'):
            _dispatch_admin_verification_email(req, action, notes)

        AuditLog.objects.create(
            action=f"ADMIN_VERIFICATION_{action.upper()}",
            performed_by=request.user,
            details={"verification_id": req.id, "reference": req.reference_number}
        )
        messages.success(request, f"Verification {req.reference_number} marked as '{action}'.")
        return redirect('admin_portal:verifications')

# ── verification details ──────────────────────────────────────────────────────

class AdminVerificationDetailView(SuperAdminRequiredMixin, TemplateView):
    """Full detail page for a single verification request."""
    template_name = "admin_portal/verification_detail.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        lookup = {'public_id': self.kwargs['public_id']} if 'public_id' in self.kwargs else {'pk': self.kwargs['pk']}
        verification = get_object_or_404(
            VerificationRequest.objects.select_related(
                'requester', 'target_subject', 'result', 'result__verified_by'
            ),
            **lookup
        )
        ctx['verification'] = verification
        ctx['has_result'] = hasattr(verification, 'result') and verification.result is not None
        return ctx

    def post(self, request, public_id=None, pk=None):
        lookup = {'public_id': public_id} if public_id else {'pk': pk}
        verification = get_object_or_404(VerificationRequest, **lookup)
        action = request.POST.get('action', '')
        notes  = request.POST.get('notes', '').strip()

        if action not in ('in_progress', 'complete', 'reject'):
            messages.error(request, "Invalid action.")
            return redirect('admin_portal:verification_detail', public_id=verification.public_id)

        if action == 'complete':
            verification.status = 'completed'
            if not hasattr(verification, 'result') or verification.result is None:
                VerificationResult.objects.get_or_create(
                    request=verification,
                    defaults={
                        'outcome': 'verified',
                        'summary': notes or 'Official verification confirmed and approved by administrator.',
                        'verified_by': request.user,
                        'verified_at': timezone.now(),
                        'details': {
                            'registry_status': 'verified',
                            'record_status': 'authentic',
                            'officer_advisory': 'Verified and approved by system administration.'
                        }
                    }
                )
        elif action == 'reject':
            verification.status = 'rejected'
        elif action == 'in_progress':
            verification.status = 'in_progress'

        if notes:
            verification.notes = notes
        verification.save(update_fields=['status', 'notes', 'updated_at'])

        if action in ('complete', 'reject'):
            _dispatch_admin_verification_email(verification, action, notes)

        AuditLog.objects.create(
            action=f"ADMIN_VERIFICATION_{action.upper()}",
            performed_by=request.user,
            details={"verification_id": verification.id, "reference": verification.reference_number}
        )
        messages.success(request, f"Verification {verification.reference_number} updated to '{action}'.")
        return redirect('admin_portal:verification_detail', public_id=verification.public_id)

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
            elif verified_filter == 'pending':
                qs = qs.filter(verification_status='pending')
            elif verified_filter == 'rejected':
                qs = qs.filter(verification_status='rejected')
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
        profile = get_object_or_404(
            EmployerProfile.objects.select_related('user'),
            user__public_id=self.kwargs['public_id']
        )

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
        bulk_qs = BulkCheckUpload.objects.filter(employer=profile).order_by('-created_at')
        ctx['bulk_uploads'] = Paginator(bulk_qs, 10).get_page(
            self.request.GET.get('bulk_page', 1)
        )

        ctx['profile'] = profile
        ctx['team_members'] = team_members
        ctx['active_tab'] = self.request.GET.get('tab', 'login')
        # Credit Subscription Plan Support & Entitlement State
        if Plan:
            ctx['available_plans'] = Plan.objects.filter(is_active=True).order_by('display_order', 'price_kobo')
            active_sub = get_active_subscription(profile.user)
            ctx['active_subscription'] = active_sub
            ctx['user_active_plan_id'] = active_sub.plan.pk if active_sub else None
        else:
            ctx['available_plans'] = []
            ctx['active_subscription'] = None
            ctx['user_active_plan_id'] = None
        ctx['free_quota'] = FreeUsageQuota.for_user(profile.user)
        ctx['site_settings'] = SiteSettings.get()

        service_rules = UserServiceAccess.objects.filter(user=profile.user)
        ctx['service_access_rules'] = service_rules
        ctx['service_access_rules_json'] = json.dumps([
            {'service': r.service, 'is_restricted': r.is_restricted}
            for r in service_rules
        ])
        ctx['service_choices'] = UserServiceAccess.SERVICE_CHOICES
        from payments.services import get_user_prepaid_balance
        from payments.models import Transaction
        ctx['employer_prepaid_balance'] = get_user_prepaid_balance(profile.user)
        ctx['employer_transactions'] = Transaction.objects.filter(user=profile.user).order_by('-created_at')[:10]
        return ctx


class AdminEmployerActivityExportView(SuperAdminRequiredMixin, View):
    """Printable activity export for an employer account."""
    def get(self, request, public_id):

        profile = get_object_or_404(
            EmployerProfile.objects.select_related('user'),
            user__public_id=public_id
        )
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


class AdminEmployerLegacyRedirectView(SuperAdminRequiredMixin, View):
    """Backward-compatible redirect from integer PK to UUID-based employer detail."""
    def get(self, request, pk):
        profile = get_object_or_404(EmployerProfile.objects.select_related('user'), pk=pk)
        return redirect('admin_portal:employer_detail', public_id=profile.user.public_id)



class AdminEmployerCACDocumentView(SuperAdminRequiredMixin, View):
    """
    Secure document stream proxy for viewing employer CAC incorporation documents.
    Serves the uploaded CAC document inline in browser without forced download.
    """
    def get(self, request, public_id):
        profile = get_object_or_404(
            EmployerProfile.objects.select_related('user'),
            user__public_id=public_id
        )
        if not profile.cac_document:
            raise Http404("No CAC document has been uploaded for this employer.")

        try:
            doc_file = profile.cac_document.open('rb')
        except Exception:
            raise Http404("Could not open the requested CAC document.")

        ext = profile.cac_document.name.split('.')[-1].lower() if '.' in profile.cac_document.name else 'pdf'
        content_type, _ = mimetypes.guess_type(profile.cac_document.name)
        if not content_type:
            content_type = 'application/pdf' if ext == 'pdf' else 'image/jpeg'

        as_download = request.GET.get('download') == '1'
        disposition = 'attachment' if as_download else 'inline'
        safe_name = f"CAC_{slugify(profile.company_name) or 'document'}.{ext}"

        response = HttpResponse(doc_file.read(), content_type=content_type)
        response['Content-Disposition'] = f'{disposition}; filename="{safe_name}"'
        response['X-Frame-Options'] = 'SAMEORIGIN'
        doc_file.close()
        return response

class AdminEmployerActionView(SuperAdminRequiredMixin, View):
    """POST: verify, unverify, or toggle billing exemption for an employer profile."""
    def post(self, request, public_id):
        profile = get_object_or_404(
            EmployerProfile.objects.select_related('user'),
            user__public_id=public_id
        )
        action = request.POST.get('action', '')
        if action == 'verify':
            profile.is_verified = True
            profile.verification_status = 'verified'
            profile.rejection_reason = ''
            profile.verified_at = timezone.now()
            # Default to candidate checks waived on verification if not specified
            selected_services = request.POST.getlist('exempt_services')
            profile.exempt_services = selected_services if selected_services else ['check']
            if not profile.billing_exempt_notes:
                profile.billing_exempt_notes = "Verified Company Complimentary Access"
            profile.save(update_fields=['is_verified', 'verification_status', 'rejection_reason', 'verified_at', 'exempt_services', 'billing_exempt_notes'])
            msg = f"Employer '{profile.company_name}' verified with complimentary service entitlements."
        elif action == 'reject':
            profile.is_verified = False
            profile.verification_status = 'rejected'
            reason = request.POST.get('rejection_reason', '').strip()
            profile.rejection_reason = reason if reason else 'CAC registration document or details could not be validated.'
            profile.save(update_fields=['is_verified', 'verification_status', 'rejection_reason'])
            msg = f"CAC verification declined for '{profile.company_name}'."
        elif action == 'unverify':
            profile.is_verified = False
            profile.verification_status = 'unverified'
            profile.save(update_fields=['is_verified', 'verification_status'])
            msg = f"Employer '{profile.company_name}' unverified."
        elif action == 'update_billing_exempt':
            profile.is_billing_exempt = request.POST.get('is_billing_exempt') == 'on'
            profile.exempt_services = request.POST.getlist('exempt_services')
            profile.billing_exempt_notes = request.POST.get('billing_exempt_notes', '').strip()
            profile.save(update_fields=['is_billing_exempt', 'exempt_services', 'billing_exempt_notes', 'updated_at'])
            count = len(profile.exempt_services)
            msg = f"Service entitlements updated for '{profile.company_name}' ({count} service(s) complimentary)."
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
        # Return back to detail page if requested
        next_url = request.POST.get('next')
        if next_url:
            return redirect(next_url)
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
    """POST: cancel, revoke, or reactivate a subscription."""
    def post(self, request, pk):
        sub = get_object_or_404(Subscription, pk=pk)
        action = request.POST.get('action', 'cancel')
        reason = request.POST.get('reason', '').strip()
        next_url = request.POST.get('next', '').strip()
        if action in ('cancel', 'revoke'):
            sub.status = 'cancelled'
            sub.save(update_fields=['status'])
            AuditLog.objects.create(
                action="ADMIN_SUBSCRIPTION_CANCEL",
                performed_by=request.user,
                details={"subscription_id": str(sub.id), "user": sub.user.username, "plan": sub.plan.name if sub.plan else "—", "reason": reason or "Admin cancellation/revocation"}
            )
            messages.success(request, f"Subscription '{sub.plan.name if sub.plan else 'Plan'}' for '{sub.user.username}' has been revoked.")
        elif action == 'reactivate':
            sub.status = 'active'
            sub.save(update_fields=['status'])
            AuditLog.objects.create(
                action="ADMIN_SUBSCRIPTION_REACTIVATE",
                performed_by=request.user,
                details={"subscription_id": str(sub.id), "user": sub.user.username}
            )
            messages.success(request, f"Subscription for '{sub.user.username}' reactivated.")
        else:
            messages.error(request, "Invalid action.")
        if next_url:
            return redirect(next_url)
        referer = request.META.get('HTTP_REFERER')
        if referer:
            return redirect(referer)
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
        credit_val   = request.POST.get('credit_value_naira', '0').strip()
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
            credit_val_int = int(float(credit_val))
        except (ValueError, TypeError):
            credit_val_int = 0

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
        plan.credit_value_naira = credit_val_int
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


class AdminPlanToggleView(SuperAdminRequiredMixin, View):
    """Toggle a Plan's is_active flag (activate / deactivate)."""

    def post(self, request, pk):
        if not Plan:
            messages.error(request, "Plan model not available.")
            return redirect('admin_portal:plans')

        plan = get_object_or_404(Plan, pk=pk)
        plan.is_active = not plan.is_active
        plan.save(update_fields=['is_active'])

        state_label = "activated" if plan.is_active else "deactivated"
        messages.success(request, f"Plan '{plan.name}' has been {state_label}.")

        log_admin_action(
            action=f'PLAN_{state_label.upper()}',
            action_type='PLAN_MGMT',
            performed_by=request.user,
            request=request,
            details={'plan_id': plan.pk, 'plan_name': plan.name, 'new_state': plan.is_active},
        )
        return redirect('admin_portal:plans')


class AdminCreditSubscriptionView(SuperAdminRequiredMixin, View):
    """
    POST: Manually credit (assign) a subscription plan to a user.
    Called from the user detail quick-actions panel.
    """
    def post(self, request, public_id):
        
        user = get_object_or_404(User, public_id=public_id)
        plan_id = request.POST.get('plan_id', '').strip()
        duration_days = request.POST.get('duration_days', '30').strip()
        reason = request.POST.get('reason', 'Admin credit').strip()
        next_url = request.POST.get('next', '').strip()
        def _redirect_response():
            if next_url:
                return redirect(next_url)
            return redirect('admin_portal:user_detail', public_id=public_id)
        if not plan_id:
            messages.error(request, "Please select a plan.")
            return _redirect_response()
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
            return _redirect_response()
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

        # Allocate monthly wallet credit if included in plan
        if getattr(plan, 'credit_value_naira', 0) and plan.credit_value_naira > 0:
            import uuid
            from payments.models import Transaction
            Transaction.objects.create(
                user=user,
                reference=f"VNG-SUB-CREDIT-{uuid.uuid4().hex[:10].upper()}",
                amount_kobo=int(plan.credit_value_naira * 100),
                currency='NGN',
                status='success',
                is_active=True,
                paystack_response={
                    'data': {
                        'metadata': {
                            'subscription_id': str(sub.pk),
                            'plan_name': plan.name,
                            'type': 'plan_credit_allowance',
                        }
                    }
                }
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
        return _redirect_response()


class AdminUserWalletTopupView(SuperAdminRequiredMixin, View):
    """
    POST: Manually top up / credit Pay-As-You-Go wallet balance in Naira (₦) for a user or employer.
    Creates an active, successful Transaction and logs the audit event.
    """
    def post(self, request, public_id):
        import uuid
        from payments.models import Transaction, PaymentAuditLog

        user = get_object_or_404(User, public_id=public_id)
        amount_str = request.POST.get('amount_naira', '').strip()
        reason = request.POST.get('reason', '').strip() or 'Admin Wallet Top-Up'
        next_url = request.POST.get('next', '').strip()

        def _redirect_response():
            if next_url:
                return redirect(next_url)
            return redirect('admin_portal:user_detail', public_id=public_id)

        try:
            amount_naira = float(amount_str)
            if amount_naira <= 0:
                raise ValueError()
        except (ValueError, TypeError):
            messages.error(request, "Please enter a valid positive Naira amount to top up.")
            return _redirect_response()

        amount_kobo = int(round(amount_naira * 100))
        ref = f"VNG-BAL-{uuid.uuid4().hex[:12].upper()}"

        tx = Transaction.objects.create(
            user=user,
            reference=ref,
            amount_kobo=amount_kobo,
            currency='NGN',
            status='success',
            is_active=True,
            paystack_response={
                'data': {
                    'metadata': {
                        'type': 'admin_manual_topup',
                        'service': 'topup',
                        'credited_by': request.user.username,
                        'reason': reason,
                        'amount_naira': amount_naira,
                    }
                }
            }
        )

        PaymentAuditLog.objects.create(
            action='PAYMENT_SUCCESS',
            user=user,
            transaction=tx,
            details={
                'amount_naira': amount_naira,
                'amount_kobo': amount_kobo,
                'reference': ref,
                'credited_by': request.user.username,
                'reason': reason,
                'type': 'admin_manual_topup',
            }
        )

        log_admin_action(
            action='USER_WALLET_TOPUP',
            action_type='ADMIN',
            performed_by=request.user,
            target_user=user,
            request=request,
            details={
                'amount_naira': amount_naira,
                'reference': ref,
                'reason': reason,
            }
        )

        messages.success(
            request,
            f"Successfully credited ₦{amount_naira:,.2f} to {user.get_full_name() or user.username}'s PAYG wallet ({reason})."
        )
        return _redirect_response()
    

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

        # --- Audit log with filters and pagination ---
        q            = self.request.GET.get('q', '').strip()
        action_type  = self.request.GET.get('action_type', '').strip()
        date_from    = self.request.GET.get('date_from', '').strip()
        date_to      = self.request.GET.get('date_to', '').strip()

        audit_qs = AuditLog.objects.select_related('performed_by').order_by('-timestamp')

        if q:
            audit_qs = audit_qs.filter(
                Q(action__icontains=q) |
                Q(performed_by__username__icontains=q)
            )
        if action_type:
            audit_qs = audit_qs.filter(action_type=action_type)
        if date_from:
            try:
                audit_qs = audit_qs.filter(timestamp__date__gte=date_from)
            except Exception:
                pass
        if date_to:
            try:
                audit_qs = audit_qs.filter(timestamp__date__lte=date_to)
            except Exception:
                pass

        paginator = Paginator(audit_qs, 30)
        ctx['audit_page'] = paginator.get_page(self.request.GET.get('audit_page', 1))

        # --- Summary panels (non-paginated, fixed count) ---
        ctx['recent_reports'] = FraudReport.objects.select_related('reporter').order_by('-created_at')[:20]
        ctx['recent_verifications'] = VerificationRequest.objects.select_related('requester').order_by('-created_at')[:20] if VerificationRequest else []
        ctx['recent_users'] = User.objects.order_by('-date_joined')[:15]

        # --- Filters state ---
        ctx['q'] = q
        ctx['action_type'] = action_type
        ctx['date_from'] = date_from
        ctx['date_to'] = date_to
        ctx['action_type_choices'] = AuditLog.objects.values_list('action_type', flat=True).distinct().order_by('action_type')
        ctx['total_audit'] = audit_qs.count()

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
        config.free_access_mode = request.POST.get('free_access_mode') == 'on'

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

        site.free_tier_enabled = request.POST.get('free_tier_enabled') == 'on'
        site.maintenance_mode = request.POST.get('maintenance_mode') == 'on'

        # Global Service Entitlement Toggles
        valid_modes = ('paid', 'free')
        site.service_quick_check = request.POST.get('service_quick_check', site.service_quick_check)
        if site.service_quick_check not in valid_modes:
            site.service_quick_check = 'paid'

        site.service_staff_check = request.POST.get('service_staff_check', site.service_staff_check)
        if site.service_staff_check not in valid_modes:
            site.service_staff_check = 'paid'

        site.service_bulk_upload = request.POST.get('service_bulk_upload', site.service_bulk_upload)
        if site.service_bulk_upload not in valid_modes:
            site.service_bulk_upload = 'paid'

        site.service_business_verification = request.POST.get('service_business_verification', site.service_business_verification)
        if site.service_business_verification not in valid_modes:
            site.service_business_verification = 'paid'

        site.service_public_check = request.POST.get('service_public_check', site.service_public_check)
        if site.service_public_check not in valid_modes:
            site.service_public_check = 'paid'

        site.service_certificate_creation = request.POST.get('service_certificate_creation', site.service_certificate_creation)
        if site.service_certificate_creation not in valid_modes:
            site.service_certificate_creation = 'paid'

        site.service_certificate_verify = request.POST.get('service_certificate_verify', site.service_certificate_verify)
        if site.service_certificate_verify not in valid_modes:
            site.service_certificate_verify = 'paid'

        site.service_monitoring = request.POST.get('service_monitoring', site.service_monitoring)
        if site.service_monitoring not in valid_modes:
            site.service_monitoring = 'paid'

        try:
            site.price_public_check = max(0, int(request.POST.get('price_public_check', site.price_public_check)))
            site.price_person_check = max(0, int(request.POST.get('price_person_check', site.price_person_check)))
            site.price_staff_check_standard = max(0, int(request.POST.get('price_staff_check_standard', site.price_staff_check_standard)))
            site.price_staff_check_enhanced = max(0, int(request.POST.get('price_staff_check_enhanced', site.price_staff_check_enhanced)))
            site.price_trustpass_1yr = max(0, int(request.POST.get('price_trustpass_1yr', site.price_trustpass_1yr)))
            site.price_trustpass_3yr = max(0, int(request.POST.get('price_trustpass_3yr', site.price_trustpass_3yr)))
            site.price_verification_basic = max(0, int(request.POST.get('price_verification_basic', site.price_verification_basic)))
            site.price_verification_business = max(0, int(request.POST.get('price_verification_business', site.price_verification_business)))
            site.price_certificate_verify = max(0, int(request.POST.get('price_certificate_verify', site.price_certificate_verify)))
            site.price_monitoring_annual = max(0, int(request.POST.get('price_monitoring_annual', site.price_monitoring_annual)))
            site.price_bulk_check_per_row = max(0, int(request.POST.get('price_bulk_check_per_row', site.price_bulk_check_per_row)))
        except (ValueError, TypeError):
            pass

        site.save()

        AuditLog.objects.create(
            action="ADMIN_SITE_SETTINGS_UPDATE",
            performed_by=request.user,
            details={
                "free_tier_enabled": site.free_tier_enabled,
                "free_check_limit": site.free_check_limit,
                "service_quick_check": site.service_quick_check,
                "service_staff_check": site.service_staff_check,
                "service_bulk_upload": site.service_bulk_upload,
                "service_business_verification": site.service_business_verification,
                "service_public_check": site.service_public_check,
                "service_certificate_creation": site.service_certificate_creation,
                "service_certificate_verify": site.service_certificate_verify,
                "service_monitoring": site.service_monitoring,
            }
        )
        messages.success(request, "Global site settings & service entitlements updated successfully.")
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
        monitoring_filter = self.request.GET.get('monitoring', '')
        q = self.request.GET.get('q', '').strip()

        if status_filter:
            qs = qs.filter(status=status_filter)
        if level_filter:
            qs = qs.filter(check_level=level_filter)
        if monitoring_filter == 'active':
            qs = qs.filter(is_monitoring_active=True, monitoring_expires_at__gt=timezone.now())
        elif monitoring_filter == 'inactive':
            qs = qs.filter(Q(is_monitoring_active=False) | Q(monitoring_expires_at__lte=timezone.now()))
        if q:
            qs = qs.filter(
                Q(certificate_id__icontains=q) |
                Q(holder__username__icontains=q) |
                Q(holder__email__icontains=q) |
                Q(subject__name__icontains=q)
            )
        paginator = Paginator(qs, 30)
        page = self.request.GET.get('page', 1)
        ctx['certificates'] = paginator.get_page(page)
        ctx['status_filter'] = status_filter
        ctx['level_filter'] = level_filter
        ctx['monitoring_filter'] = monitoring_filter
        ctx['q'] = q
        ctx['status_choices'] = VerificationCertificate.STATUS_CHOICES
        ctx['level_choices'] = VerificationCertificate.CHECK_LEVEL_CHOICES
        ctx['total'] = qs.count()
        ctx['pending_count'] = VerificationCertificate.objects.filter(status='pending').count()
        ctx['active_monitoring_count'] = VerificationCertificate.objects.filter(is_monitoring_active=True, monitoring_expires_at__gt=timezone.now()).count()
        ctx['now'] = timezone.now()
        return ctx


class AdminCertificateLegacyRedirectView(SuperAdminRequiredMixin, View):
    """Backward-compatible redirect from integer PK to UUID-based certificate detail."""
    def get(self, request, pk):
        if not VerificationCertificate:
            raise Http404("Certificate model not available.")
        cert = get_object_or_404(VerificationCertificate, pk=pk)
        return redirect('admin_portal:certificate_detail', public_id=cert.public_id)


class AdminCertificateActionView(SuperAdminRequiredMixin, View):
    """Activate, suspend, or revoke a certificate."""

    def post(self, request, public_id=None, pk=None):
        if not VerificationCertificate:
            return JsonResponse({'ok': False, 'error': 'Certificate model not available.'}, status=400)

        lookup = {'public_id': public_id} if public_id else {'pk': pk}
        cert = get_object_or_404(VerificationCertificate, **lookup)
        action = request.POST.get('action', '').strip()
        reason = request.POST.get('reason', '').strip()

        now = timezone.now()

        if action == 'activate':
            cert.status = 'active'
            cert.issued_at = cert.issued_at or now
            cert.expires_at = (cert.issued_at or now) + relativedelta(years=cert.expiry_years)
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
        elif action == 'remove_monitoring':
            cert.is_monitoring_active = False
            cert.save(update_fields=['is_monitoring_active', 'updated_at'])
            log_admin_action(
                action='UPDATE_SERVICE_UNLISTED',
                action_type='CERTIFICATE_MGMT',
                performed_by=request.user,
                target_user=cert.holder,
                request=request,
                details={'certificate_id': cert.certificate_id, 'reason': reason},
                description=f"Admin removed certificate {cert.certificate_id} from Continuous Update Service. Reason: {reason}",
            )
            return JsonResponse({
                'ok': True,
                'action': action,
                'status': cert.status,
                'certificate_id': cert.certificate_id,
                'message': f'Certificate {cert.certificate_id} removed from Continuous Update Service successfully.',
            })
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


class AdminCertificateDetailView(SuperAdminRequiredMixin, TemplateView):
    """Full certificate detail — holder info, history, and officer action buttons."""
    template_name = "admin_portal/certificate_detail.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        if not VerificationCertificate:
            ctx['no_model'] = True
            return ctx
        lookup = {'public_id': self.kwargs['public_id']} if 'public_id' in self.kwargs else {'pk': self.kwargs['pk']}
        cert = get_object_or_404(
            VerificationCertificate.objects.select_related('holder', 'subject'),
            **lookup
        )
        ctx['cert'] = cert
        ctx['now'] = timezone.now()
        ctx['action_url'] = f'/admin-portal/certificates/{cert.public_id}/action/'
        # Robust multi-strategy lookup for application audit log (SQLite & Postgres compatible)
                # Robust lookup for application audit log strictly matching THIS certificate_id
        app_log = None
        logs = AuditLog.objects.filter(
            action="TRUSTPASS_APPLICATION_SUBMITTED"
        ).order_by('-timestamp')[:100]
        for l in logs:
            det = l.details
            if isinstance(det, str):
                try:
                    det = json.loads(det)
                except Exception:
                    det = {}
            elif not isinstance(det, dict):
                det = {}
            if det.get('certificate_id') == cert.certificate_id:
                app_log = l
                break

        app_details = {}
        if app_log:
            if isinstance(app_log.details, dict):
                app_details = app_log.details
            elif isinstance(app_log.details, str):
                try:
                    app_details = json.loads(app_log.details)
                except Exception:
                    app_details = {}

        ctx['app_log'] = app_log
        ctx['app_details'] = app_details

        # Extract full ID number for national database verification
        id_number = (
            app_details.get('nin') or
            app_details.get('id_number') or
            app_details.get('nin_masked') or
            ''
        )
        ctx['id_number'] = id_number

        # Pre-format candidate contact address cleanly for template rendering
        res_addr = (
            app_details.get('residential_address') or
            app_details.get('contact_address') or
            app_details.get('address') or
            ''
        )
        city = app_details.get('residential_city') or app_details.get('city') or ''
        state = app_details.get('residential_state') or app_details.get('state') or ''
        parts = [p.strip() for p in [res_addr, city, state] if p and str(p).strip()]
        ctx['candidate_contact_address'] = ', '.join(parts) if parts else '?'

        # Document detection strictly for this certificate
        doc_pid = app_details.get('doc_public_id') or ''
        has_doc = bool(doc_pid)
        ext = doc_pid.split('.')[-1].lower() if '.' in doc_pid else 'jpg'

        ctx['has_doc'] = has_doc
        ctx['is_pdf'] = (ext == 'pdf')
        ctx['alias_flag'] = app_details.get('alias_flag', False)
        ctx['previous_registered_name'] = app_details.get('previous_registered_name', '')
        return ctx


class AdminCertificateDocumentView(SuperAdminRequiredMixin, View):
    """
    Secure document stream proxy for verification officers.
    Serves the candidate's uploaded identity proof inline in the browser tab
    (or as file download if ?download=1) without exposing raw Cloudinary CDN or 404ing.
    """
    def get(self, request, public_id=None, pk=None):
        
        if not VerificationCertificate:
            raise Http404("Certificate model not available.")
        lookup = {'public_id': public_id} if public_id else {'pk': pk}
        cert = get_object_or_404(VerificationCertificate, **lookup)
        # Locate the application audit log strictly for THIS certificate
        app_log = None
        for l in AuditLog.objects.filter(action="TRUSTPASS_APPLICATION_SUBMITTED").order_by('-timestamp')[:200]:
            det = l.details
            if isinstance(det, str):
                try:
                    det = json.loads(det)
                except Exception:
                    det = {}
            elif not isinstance(det, dict):
                det = {}
            if det.get('certificate_id') == cert.certificate_id:
                app_log = l
                break
        if not app_log:
            messages.warning(request, f"No application submission record found for certificate {cert.certificate_id}.")
            return redirect('admin_portal:certificate_detail', pk=cert.pk)

        det = app_log.details
        if isinstance(det, str):
            try:
                det = json.loads(det)
            except Exception:
                det = {}
        elif not isinstance(det, dict):
            det = {}

        doc_pid = det.get('doc_public_id') or ''
        if not doc_pid:
            messages.warning(request, f"No identity document proof was attached to application {cert.certificate_id}.")
            return redirect('admin_portal:certificate_detail', pk=cert.pk)

        # Determine file extension and MIME type
        ext = doc_pid.split('.')[-1].lower() if '.' in doc_pid else 'jpg'
        content_type, _ = mimetypes.guess_type(f"proof.{ext}")
        if not content_type:
            content_type = 'application/pdf' if ext == 'pdf' else 'image/jpeg'
        as_download = request.GET.get('download') == '1'
        disposition_type = 'attachment' if as_download else 'inline'
        safe_filename = f"{cert.certificate_id}_proof.{ext}"

        # 1. Local storage check
        local_path = os.path.join(settings.MEDIA_ROOT, doc_pid)
        if os.path.exists(local_path):
            with open(local_path, 'rb') as f:
                resp = HttpResponse(f.read(), content_type=content_type)
                resp['Content-Disposition'] = f'{disposition_type}; filename="{safe_filename}"'
                return resp

        # 2. Cloudinary storage stream
        try:
            storage = get_storage_service()
            res_type = 'raw' if ext in ['pdf', 'doc', 'docx'] else 'image'
            signed_url = storage.generate_signed_url(public_id=doc_pid, format=ext, resource_type=res_type, attachment=True)
            req_obj = urllib.request.Request(signed_url, headers={'User-Agent': 'VerifyNG-Officer/1.0'})
            with urllib.request.urlopen(req_obj, timeout=20) as cloud_resp:
                content = cloud_resp.read()
                resp = HttpResponse(content, content_type=content_type)
                resp['Content-Disposition'] = f'{disposition_type}; filename="{safe_filename}"'
                return resp
        except Exception as e:
            logger.error("Failed streaming verification document for %s: %s", cert.certificate_id, e)
            messages.error(request, f"Unable to retrieve document proof for {cert.certificate_id} from storage.")
            return redirect('admin_portal:certificate_detail', pk=cert.pk)


class AdminMenuAccessView(SuperAdminRequiredMixin, View):
    """
    Manage which Django permission groups apply to moderator/officer sub-admins.
    Lists all non-superuser staff users and their assigned groups.
    Super-admin can add or remove users from groups via this view.
    No new model required — uses Django's built-in auth.Group system.
    """
    template_name = "admin_portal/menu_access.html"

    def get(self, request):
        
        staff_users = User.objects.filter(
            role__in=['moderator', 'officer']
        ).prefetch_related('groups').order_by('role', 'username')
        all_groups = Group.objects.all().order_by('name')
        return render(request, self.template_name, {
            'staff_users': staff_users,
            'all_groups': all_groups,
        })

    def post(self, request):

        user_id = request.POST.get('user_id')
        group_id = request.POST.get('group_id')
        action = request.POST.get('action', '')  # 'add' or 'remove'

        if not user_id or not group_id or action not in ('add', 'remove'):
            return JsonResponse({'ok': False, 'error': 'Invalid request.'}, status=400)

        target_user = get_object_or_404(User, pk=user_id)
        group = get_object_or_404(Group, pk=group_id)

        if action == 'add':
            target_user.groups.add(group)
            msg = f"'{group.name}' added to {target_user.get_full_name() or target_user.username}."
        else:
            target_user.groups.remove(group)
            msg = f"'{group.name}' removed from {target_user.get_full_name() or target_user.username}."

        AuditLog.objects.create(
            action=f"ADMIN_GROUP_{action.upper()}",
            performed_by=request.user,
            details={
                'target_username': target_user.username,
                'group': group.name,
                'action': action,
            }
        )
        return JsonResponse({
            'ok': True,
            'message': msg,
            'action': action,
            'group_id': group.pk,
            'group_name': group.name,
            'user_id': target_user.pk,
        })

    
# ─────────────────────────────────────────────────────────────────────────────
# Financial Reporting — Modern Executive Statement PDF Layout
# ─────────────────────────────────────────────────────────────────────────────

class RoundedCard(Flowable):
    """Clean rounded-corner container flowable for statement metric cards."""
    def __init__(self, table, width, bg_color='#f8fafc', border_color='#cbd5e1', radius=8):
        super().__init__()
        self.table = table
        self.width = width
        self.bg_color = colors.HexColor(bg_color)
        self.border_color = colors.HexColor(border_color)
        self.radius = radius

    def wrap(self, availWidth, availHeight):
        w, h = self.table.wrap(self.width - 24, availHeight)
        self.table_w = w
        self.table_h = h
        self.height = h + 16
        return self.width, self.height

    def draw(self):
        self.canv.saveState()
        self.canv.setFillColor(self.bg_color)
        self.canv.setStrokeColor(self.border_color)
        self.canv.setLineWidth(0.8)
        self.canv.roundRect(0, 0, self.width, self.height, self.radius, fill=1, stroke=1)
        self.canv.restoreState()
        self.table.drawOn(self.canv, 12, 8)


class AdminFinancialReportView(SuperAdminRequiredMixin, TemplateView):
    """
    Dynamic financial reporting dashboard with CSV and PDF export.
    Covers: revenue KPIs, monthly breakdown, plan breakdown, transaction ledger.
    """
    template_name = "admin_portal/financial_report.html"

    def _get_date_range(self, request):
        """Return (date_from, date_to) as aware datetimes from GET params or sensible defaults."""
        now = timezone.now()
        try:
            date_from = datetime.strptime(request.GET.get('date_from', ''), '%Y-%m-%d')
            date_from = timezone.make_aware(date_from.replace(hour=0, minute=0, second=0))
        except ValueError:
            date_from = (now - timedelta(days=90)).replace(hour=0, minute=0, second=0, microsecond=0)
        try:
            date_to = datetime.strptime(request.GET.get('date_to', ''), '%Y-%m-%d')
            date_to = timezone.make_aware(date_to.replace(hour=23, minute=59, second=59))
        except ValueError:
            date_to = now
        return date_from, date_to

    @classmethod
    def _apply_filters(cls, qs, request):
        status_filter = request.GET.get('status', '').strip()
        type_filter = request.GET.get('plan', '').strip() or request.GET.get('type', '').strip()

        if status_filter:
            qs = qs.filter(status=status_filter)

        if type_filter:
            if type_filter == 'payg':
                qs = qs.filter(plan__isnull=True)
            elif type_filter in ('subscription', 'subscriptions'):
                qs = qs.filter(plan__isnull=False)
            elif type_filter in ('bulk_upload', 'bulk_check'):
                qs = qs.filter(
                    Q(paystack_response__data__metadata__service__in=['bulk_upload', 'bulk_check']) |
                    Q(paystack_response__metadata__service__in=['bulk_upload', 'bulk_check'])
                )
            elif type_filter in ('monitoring', 'update_service'):
                qs = qs.filter(
                    Q(paystack_response__data__metadata__service='monitoring') |
                    Q(paystack_response__metadata__service='monitoring')
                )
            elif type_filter == 'certificate':
                qs = qs.filter(
                    Q(paystack_response__data__metadata__service='certificate') |
                    Q(paystack_response__metadata__service='certificate')
                )
            elif type_filter == 'certificate_verify':
                qs = qs.filter(
                    Q(paystack_response__data__metadata__service='certificate_verify') |
                    Q(paystack_response__metadata__service='certificate_verify')
                )
            elif type_filter == 'staff_check':
                qs = qs.filter(
                    Q(paystack_response__data__metadata__service='staff_check') |
                    Q(paystack_response__metadata__service='staff_check')
                )
            elif type_filter in ('verification', 'business_verification'):
                qs = qs.filter(
                    Q(paystack_response__data__metadata__service__in=['verification', 'business_verification']) |
                    Q(paystack_response__metadata__service__in=['verification', 'business_verification'])
                )
            elif type_filter in ('public_check', 'person_check', 'check'):
                qs = qs.filter(
                    Q(paystack_response__data__metadata__service__in=['public_check', 'check', 'person_check', 'quick_check']) |
                    Q(paystack_response__metadata__service__in=['public_check', 'check', 'person_check', 'quick_check'])
                )
            elif type_filter == 'topup':
                qs = qs.filter(
                    Q(paystack_response__data__metadata__service='topup') |
                    Q(paystack_response__metadata__service='topup') |
                    Q(reference__startswith='VNG-BAL-')
                )
            elif type_filter.isdigit():
                qs = qs.filter(plan__pk=type_filter)
            elif type_filter.startswith('plan_'):
                qs = qs.filter(plan__pk=type_filter.replace('plan_', ''))

        return qs, status_filter, type_filter

    def _build_context(self, request):

        date_from, date_to = self._get_date_range(request)

        qs = Transaction.objects.filter(
            created_at__gte=date_from,
            created_at__lte=date_to,
            # NOTE: Do NOT filter by is_active here. is_active on Transaction
            # tracks whether a pre-paid credit has been consumed/spent — it is
            # NOT a soft-delete flag. A consumed transaction (is_active=False)
            # is still a real payment that admin must see in financial reports.
        ).select_related('user', 'plan').order_by('-created_at')

        qs, status_filter, plan_filter = self._apply_filters(qs, request)

        all_plans = Plan.objects.filter(is_active=True).order_by('name')
        platform = PlatformConfiguration.get()

        # KPI aggregates (success only for revenue)
        success_qs = qs.filter(status='success')
        refund_qs  = refund_qs_full = qs.filter(status='refunded')

        agg = success_qs.aggregate(
            total=Sum('amount_kobo'),
            count=Count('id'),
            avg=Avg('amount_kobo'),
        )
        total_revenue_kobo  = agg['total'] or 0
        total_transactions  = agg['count'] or 0
        avg_kobo            = agg['avg'] or 0
        total_refunds_kobo  = refund_qs.aggregate(t=Sum('amount_kobo'))['t'] or 0

        # Monthly breakdown
        monthly_data = {}
        for txn in success_qs.order_by('created_at'):
            key = txn.created_at.strftime('%b %Y')
            if key not in monthly_data:
                monthly_data[key] = {'count': 0, 'revenue': 0, 'refunds': 0}
            monthly_data[key]['count'] += 1
            monthly_data[key]['revenue'] += txn.amount_kobo / 100

        for txn in refund_qs.order_by('created_at'):
            key = txn.created_at.strftime('%b %Y')
            if key not in monthly_data:
                monthly_data[key] = {'count': 0, 'revenue': 0, 'refunds': 0}
            monthly_data[key]['refunds'] += txn.amount_kobo / 100

        monthly_breakdown = [
            {
                'month':   month,
                'count':   data['count'],
                'revenue': data['revenue'],
                'refunds': data['refunds'],
                'net':     data['revenue'] - data['refunds'],
            }
            for month, data in monthly_data.items()
        ]

        # Service & Plan breakdown (granular so admin can see every product's performance)
        breakdown_dict = {}
        for txn in success_qs:
            name = txn.plan.name if txn.plan else txn.item_display_name
            if name.startswith('Certificate Monitoring'):
                name = 'Certificate Monitoring Services (TrustPass)'
            if name not in breakdown_dict:
                breakdown_dict[name] = {'count': 0, 'revenue': 0}
            breakdown_dict[name]['count'] += 1
            breakdown_dict[name]['revenue'] += txn.amount_kobo / 100

        plan_breakdown = [
            {
                'plan_name': name,
                'count':     data['count'],
                'revenue':   data['revenue'],
            }
            for name, data in sorted(breakdown_dict.items(), key=lambda x: -x[1]['revenue'])
        ]

        # Paginated ledger (all statuses matching filter)
        paginator = Paginator(qs, 50)
        page_number = request.GET.get('page', 1)
        transactions_page = paginator.get_page(page_number)

        active_subs = Subscription.objects.filter(status='active', is_active=True).count()

        return {
            'date_from_str':        date_from.strftime('%Y-%m-%d'),
            'date_to_str':          date_to.strftime('%Y-%m-%d'),
            'status_filter':        status_filter,
            'plan_filter':          plan_filter,
            'all_plans':            all_plans,
            'platform_name':        platform.platform_name,
            'company_name':         platform.company_name,
            'total_revenue_naira':  total_revenue_kobo / 100,
            'total_refunds_naira':  total_refunds_kobo / 100,
            'net_revenue_naira':    (total_revenue_kobo - total_refunds_kobo) / 100,
            'total_transactions':   total_transactions,
            'avg_transaction_naira': avg_kobo / 100,
            'active_subscriptions': active_subs,
            'monthly_breakdown':    monthly_breakdown,
            'plan_breakdown':       plan_breakdown,
            'transactions':         transactions_page,
        }

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx.update(self._build_context(self.request))
        return ctx

    def get(self, request, *args, **kwargs):
        download = request.GET.get('download', '')
        if download == 'csv':
            return self._export_csv(request)
        if download == 'pdf':
            return self._export_pdf(request)
        return super().get(request, *args, **kwargs)

    # ── CSV Export ────────────────────────────────────────────────────────────
    def _export_csv(self, request):
        
        date_from, date_to = self._get_date_range(request)
        qs = Transaction.objects.filter(
            created_at__gte=date_from,
            created_at__lte=date_to,
            # is_active is NOT a soft-delete flag on Transaction — it tracks
            # whether a pre-paid credit is still unspent. Remove the filter
            # so consumed/fulfilled payments remain visible in the CSV export.
        ).select_related('user', 'plan').order_by('-created_at')
        qs, status_filter, plan_filter = self._apply_filters(qs, request)

        response = HttpResponse(content_type='text/csv')
        fname = f"verifyng_financial_{date_from.strftime('%Y%m%d')}_{date_to.strftime('%Y%m%d')}.csv"
        response['Content-Disposition'] = f'attachment; filename="{fname}"'

        writer = csv_mod.writer(response)
        writer.writerow([
            'Reference', 'Paystack Ref', 'User', 'Plan / Service',
            'Amount (₦)', 'Currency', 'Status', 'Date'
        ])
        for txn in qs:
            writer.writerow([
                txn.reference,
                txn.paystack_reference or '—',
                txn.user.get_full_name() if txn.user else '—',
                txn.item_display_name,
                f"{txn.amount_naira:.2f}",
                txn.currency,
                txn.get_status_display(),
                txn.created_at.strftime('%Y-%m-%d %H:%M'),
            ])
        return response

    # ── PDF Export — Executive Revenue & Margins Statement (matching f_good) ──
    def _export_pdf(self, request):
        platform = PlatformConfiguration.get()
        site_name = platform.platform_name or 'VerifyNG'
        company_name = platform.company_name or 'VerifyNG Limited'

        ctx = self._build_context(request)
        buffer = io.BytesIO()

        PAGE_W, PAGE_H = A4
        MARGIN = 14 * mm
        CONTENT_W = PAGE_W - 2 * MARGIN

        doc = SimpleDocTemplate(
            buffer,
            pagesize=A4,
            leftMargin=MARGIN,
            rightMargin=MARGIN,
            topMargin=12 * mm,
            bottomMargin=14 * mm,
        )

        def add_footer(canvas, d):
            canvas.saveState()
            canvas.setFont('Helvetica', 8)
            canvas.setFillColor(colors.HexColor('#9ca3af'))
            canvas.drawCentredString(PAGE_W / 2.0, 7 * mm, f'Page {canvas._pageNumber}')
            canvas.restoreState()

        # ── Color Palette (Modern Executive Styling) ────────────────────────
        C_BLUE        = colors.HexColor('#1b7a9f')
        C_BORDER      = colors.HexColor('#e2e8f0')
        C_LINE        = colors.HexColor('#f1f5f9')
        C_TEXT_DARK   = colors.HexColor('#0f172a')
        C_TEXT_MUTED  = colors.HexColor('#64748b')
        C_GREEN       = colors.HexColor('#16a34a')
        C_RED         = colors.HexColor('#dc2626')
        C_AMBER       = colors.HexColor('#d97706')

        def th(text, align=TA_LEFT, font_size=8):
            return Paragraph(
                text,
                ParagraphStyle('TH', fontName='Helvetica-Bold', fontSize=font_size, leading=font_size + 2, textColor=colors.white, alignment=align)
            )

        def td(text, align=TA_LEFT, bold=False, color=C_TEXT_DARK, font_size=8, leading=None):
            return Paragraph(
                str(text),
                ParagraphStyle('TD', fontName='Helvetica-Bold' if bold else 'Helvetica', fontSize=font_size, leading=(leading or (font_size + 2)), textColor=color, alignment=align)
            )

        story = []

        # ── 1. HEADER (Title, Date range left | Generated on, Total transactions right) ──
        hdr_left = [
            Paragraph('REVENUE & MARGINS STATEMENT', ParagraphStyle('H1', fontName='Helvetica-Bold', fontSize=15, leading=18, textColor=C_TEXT_DARK)),
            Paragraph(f"Statement Period: {ctx['date_from_str']} to {ctx['date_to_str']}", ParagraphStyle('Sub', fontName='Helvetica', fontSize=8.5, leading=12, textColor=C_TEXT_MUTED)),
        ]
        hdr_right = [
            Paragraph(f"Generated On: {timezone.now().strftime('%d %b %Y, %H:%M %p')}", ParagraphStyle('G1', fontName='Helvetica', fontSize=8, leading=11, textColor=C_TEXT_MUTED, alignment=TA_RIGHT)),
            Paragraph(f"Total Transactions: {ctx['total_transactions']}", ParagraphStyle('G2', fontName='Helvetica', fontSize=8, leading=11, textColor=colors.HexColor('#334155'), alignment=TA_RIGHT)),
        ]
        hdr_table = Table([[hdr_left, hdr_right]], colWidths=[CONTENT_W * 0.6, CONTENT_W * 0.4])
        hdr_table.setStyle(TableStyle([
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ('LEFTPADDING', (0, 0), (-1, -1), 0),
            ('RIGHTPADDING', (0, 0), (-1, -1), 0),
            ('TOPPADDING', (0, 0), (-1, -1), 0),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 0),
        ]))
        story.append(hdr_table)
        story.append(Spacer(1, 4 * mm))

        # ── 2. SUMMARY CARD (Sleek rounded box with key metrics and green Net Profit) ──
        summary_metrics = Paragraph(
            f"Total Revenue: <font color=\"#0f172a\"><b>NGN {ctx['total_revenue_naira']:,.2f}</b></font>&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;"
            f"Avg. Transaction: <font color=\"#0f172a\"><b>NGN {ctx['avg_transaction_naira']:,.2f}</b></font>&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;"
            f"Active Subscriptions: <font color=\"#0f172a\"><b>{ctx['active_subscriptions']}</b></font>",
            ParagraphStyle('SM', fontName='Helvetica', fontSize=8.5, leading=12, textColor=colors.HexColor('#475569'))
        )
        summary_net = Paragraph(
            f"NET PROFIT: NGN {ctx['net_revenue_naira']:,.2f}",
            ParagraphStyle('SN', fontName='Helvetica-Bold', fontSize=11, leading=14, textColor=C_GREEN, alignment=TA_RIGHT)
        )
        summary_inner = Table([[summary_metrics, summary_net]], colWidths=[(CONTENT_W - 24) * 0.72, (CONTENT_W - 24) * 0.28])
        summary_inner.setStyle(TableStyle([
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('LEFTPADDING', (0, 0), (-1, -1), 0),
            ('RIGHTPADDING', (0, 0), (-1, -1), 0),
            ('TOPPADDING', (0, 0), (-1, -1), 0),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 0),
        ]))
        story.append(RoundedCard(summary_inner, width=CONTENT_W))
        story.append(Spacer(1, 5 * mm))

        # ── 3. MONTHLY & PLAN BREAKDOWNS (Side-by-side) ───────────────────────
        monthly = ctx.get('monthly_breakdown', [])
        plans = ctx.get('plan_breakdown', [])

        if monthly or plans:
            half_w = (CONTENT_W - 6 * mm) / 2

            # Monthly breakdown
            m_data = [[th('Month'), th('Txns', TA_RIGHT), th('Revenue (NGN)', TA_RIGHT), th('Net (NGN)', TA_RIGHT)]]
            for m in monthly[:6]:
                m_data.append([
                    td(m['month'], bold=True),
                    td(str(m['count']), align=TA_RIGHT),
                    td(f"{m['revenue']:,.2f}", align=TA_RIGHT, color=C_GREEN),
                    td(f"{m['net']:,.2f}", align=TA_RIGHT, bold=True)
                ])
            if not monthly:
                m_data.append([td('No monthly data', color=C_TEXT_MUTED), '', '', ''])

            m_table = Table(m_data, colWidths=[half_w * 0.32, half_w * 0.18, half_w * 0.25, half_w * 0.25])
            m_table.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), C_BLUE),
                ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
                ('TOPPADDING', (0, 0), (-1, -1), 4),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
                ('LEFTPADDING', (0, 0), (-1, -1), 4),
                ('RIGHTPADDING', (0, 0), (-1, -1), 4),
                ('LINEBELOW', (0, 1), (-1, -1), 0.5, C_LINE),
                ('BOX', (0, 0), (-1, -1), 0.5, C_BORDER),
            ]))

            # Plan breakdown
            p_data = [[th('Plan Name'), th('Txns', TA_RIGHT), th('Revenue (NGN)', TA_RIGHT)]]
            for p in plans[:6]:
                p_data.append([
                    td(p['plan_name'], bold=True),
                    td(str(p['count']), align=TA_RIGHT),
                    td(f"{p['revenue']:,.2f}", align=TA_RIGHT, color=C_GREEN, bold=True)
                ])
            if not plans:
                p_data.append([td('No plan data', color=C_TEXT_MUTED), '', ''])

            p_table = Table(p_data, colWidths=[half_w * 0.50, half_w * 0.20, half_w * 0.30])
            p_table.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), C_BLUE),
                ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
                ('TOPPADDING', (0, 0), (-1, -1), 4),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
                ('LEFTPADDING', (0, 0), (-1, -1), 4),
                ('RIGHTPADDING', (0, 0), (-1, -1), 4),
                ('LINEBELOW', (0, 1), (-1, -1), 0.5, C_LINE),
                ('BOX', (0, 0), (-1, -1), 0.5, C_BORDER),
            ]))

            breakdown_row = Table([[m_table, '', p_table]], colWidths=[half_w, 6 * mm, half_w])
            breakdown_row.setStyle(TableStyle([
                ('VALIGN', (0, 0), (-1, -1), 'TOP'),
                ('LEFTPADDING', (0, 0), (-1, -1), 0),
                ('RIGHTPADDING', (0, 0), (-1, -1), 0),
                ('TOPPADDING', (0, 0), (-1, -1), 0),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 0),
            ]))
            story.append(breakdown_row)
            story.append(Spacer(1, 5 * mm))

        # ── 4. TRANSACTION LEDGER (Ocean blue header, clean styling matching f_good) ──
        date_from_pdf, date_to_pdf = self._get_date_range(request)
        txn_qs = TxnModel.objects.filter(
            created_at__gte=date_from_pdf,
            created_at__lte=date_to_pdf,
            # is_active is NOT a soft-delete flag on Transaction — it tracks
            # whether a pre-paid credit is still unspent. Remove filter so
            # consumed/fulfilled payments appear in the PDF export too.
        ).select_related('user', 'plan').order_by('-created_at')
        txn_qs, status_filter_pdf, plan_filter_pdf = self._apply_filters(txn_qs, request)
        txn_qs = txn_qs[:200]

        ledger_rows = [[
            th('Date'),
            th('Service'),
            th('References (Ext / Ref)'),
            th('Customer'),
            th('User Paid', TA_RIGHT),
            th('Status', TA_CENTER),
            th('Net Profit', TA_RIGHT),
        ]]

        for txn in txn_qs:
            user_name = '—'
            if txn.user:
                user_name = (txn.user.get_full_name() or txn.user.username or '—')[:22]
            srv_name = txn.item_display_name[:26]
            ref_str = f"Ref: {txn.reference[:18]}" if txn.reference else '—'
            if txn.paystack_reference:
                ref_str += f"<br/>Ext: {txn.paystack_reference[:18]}"

            if txn.status == 'success':
                st_label = 'Success'
                st_color = C_GREEN
                net_val = f"NGN {txn.amount_naira:,.2f}"
                net_color = C_GREEN
            elif txn.status == 'refunded':
                st_label = 'Refunded'
                st_color = C_AMBER
                net_val = f"-NGN {txn.amount_naira:,.2f}"
                net_color = C_RED
            elif txn.status == 'failed':
                st_label = 'Failed'
                st_color = C_RED
                net_val = "NGN 0.00"
                net_color = C_TEXT_MUTED
            else:
                st_label = txn.get_status_display()
                st_color = C_TEXT_MUTED
                net_val = "NGN 0.00"
                net_color = C_TEXT_MUTED

            ledger_rows.append([
                td(txn.created_at.strftime('%d %b %Y, %H:%M'), color=colors.HexColor('#334155'), font_size=7.5),
                td(srv_name, bold=True, color=C_TEXT_DARK, font_size=8),
                td(ref_str, color=C_TEXT_MUTED, font_size=7, leading=9),
                td(user_name, color=colors.HexColor('#334155'), font_size=8),
                td(f"NGN {txn.amount_naira:,.2f}", align=TA_RIGHT, color=C_TEXT_DARK, font_size=8),
                td(st_label, align=TA_CENTER, bold=True, color=st_color, font_size=7.5),
                td(net_val, align=TA_RIGHT, bold=True, color=net_color, font_size=8),
            ])

        if not txn_qs:
            ledger_rows.append([td('No transactions in this period', color=C_TEXT_MUTED), '', '', '', '', '', ''])

        col_w = [25 * mm, 32 * mm, 40 * mm, 30 * mm, 19 * mm, 16 * mm, 20 * mm]
        t_ledger = Table(ledger_rows, colWidths=col_w, repeatRows=1)
        t_ledger.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), C_BLUE),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('TOPPADDING', (0, 0), (-1, 0), 6),
            ('BOTTOMPADDING', (0, 0), (-1, 0), 6),
            ('TOPPADDING', (0, 1), (-1, -1), 5),
            ('BOTTOMPADDING', (0, 1), (-1, -1), 5),
            ('LEFTPADDING', (0, 0), (-1, -1), 5),
            ('RIGHTPADDING', (0, 0), (-1, -1), 5),
            ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#f8fafc')]),
            ('LINEBELOW', (0, 1), (-1, -1), 0.5, C_LINE),
            ('BOX', (0, 0), (-1, -1), 0.5, C_BORDER),
        ]))
        story.append(t_ledger)

        doc.build(story, onFirstPage=add_footer, onLaterPages=add_footer)
        date_str = ctx['date_from_str'].replace('-', '') + '_' + ctx['date_to_str'].replace('-', '')
        response = HttpResponse(content_type='application/pdf')
        response['Content-Disposition'] = f'attachment; filename="VerifyNG_Financial_Statement_{date_str}.pdf"'
        response.write(buffer.getvalue())
        return response





from django.urls import path
from dashboard.admin_views import (
    # Existing
    AdminOverviewView,
    AdminUserListView,
    AdminUserToggleStatusView,
    AdminUserChangeRoleView,
    AdminAuditLogsView,
    AdminCommunicationsView,
    # Users — extended
    AdminUserDetailView,
    AdminUserHardDeleteView,
    AdminUserBlockView,
    # Reports moderation
    AdminReportsView,
    AdminReportDetailView,
    AdminReportTransitionView,
    # Disputes
    AdminDisputesView,
    AdminDisputeActionView,
    # Verifications
    AdminVerificationsView,
    AdminVerificationActionView,
    # Employer Profiles
    AdminEmployerProfilesView,
    AdminEmployerActionView,
    # Subscriptions
    AdminSubscriptionsView,
    AdminSubscriptionCancelView,
    # Analytics
    AdminAnalyticsView,
    # System Logs
    AdminSystemLogsView,
    AdminActivityLogsView,
    AdminLoginLogsView,
    # Platform Settings
    AdminPlatformSettingsView,
    AdminSiteSettingsView,
)

app_name = 'admin_portal'

urlpatterns = [
    # ── Overview Dashboard ─────────────────────────────────────────────────
    path('', AdminOverviewView.as_view(), name='overview'),

    # ── Analytics ─────────────────────────────────────────────────────────
    path('analytics/', AdminAnalyticsView.as_view(), name='analytics'),

    # ── User Management ────────────────────────────────────────────────────
    path('users/', AdminUserListView.as_view(), name='users'),
    path('users/<int:user_id>/', AdminUserDetailView.as_view(), name='user_detail'),
    path('users/<int:user_id>/toggle-status/', AdminUserToggleStatusView.as_view(), name='user_toggle_status'),
    path('users/<int:user_id>/change-role/', AdminUserChangeRoleView.as_view(), name='user_change_role'),
    path('users/<int:user_id>/block/', AdminUserBlockView.as_view(), name='user_block'),
    path('users/<int:user_id>/hard-delete/', AdminUserHardDeleteView.as_view(), name='user_hard_delete'),

    # ── Reports Moderation ─────────────────────────────────────────────────
    path('reports/', AdminReportsView.as_view(), name='reports'),
    path('reports/<int:pk>/', AdminReportDetailView.as_view(), name='report_detail'),
    path('reports/<int:pk>/transition/', AdminReportTransitionView.as_view(), name='report_transition'),

    # ── Disputes ────────────────────────────────────────────────────────────
    path('disputes/', AdminDisputesView.as_view(), name='disputes'),
    path('disputes/<int:pk>/action/', AdminDisputeActionView.as_view(), name='dispute_action'),

    # ── Verifications ───────────────────────────────────────────────────────
    path('verifications/', AdminVerificationsView.as_view(), name='verifications'),
    path('verifications/<int:pk>/action/', AdminVerificationActionView.as_view(), name='verification_action'),

    # ── Employer Profiles ───────────────────────────────────────────────────
    path('employers/', AdminEmployerProfilesView.as_view(), name='employer_profiles'),
    path('employers/<int:pk>/action/', AdminEmployerActionView.as_view(), name='employer_action'),

    # ── Subscriptions / Payments ────────────────────────────────────────────
    path('subscriptions/', AdminSubscriptionsView.as_view(), name='subscriptions'),
    path('subscriptions/<int:pk>/cancel/', AdminSubscriptionCancelView.as_view(), name='subscription_cancel'),

    # ── Logs ────────────────────────────────────────────────────────────────
    path('logs/system/', AdminSystemLogsView.as_view(), name='system_logs'),
    path('logs/activity/', AdminActivityLogsView.as_view(), name='activity_logs'),
    path('logs/login/', AdminLoginLogsView.as_view(), name='login_logs'),

    # ── Communications ──────────────────────────────────────────────────────
    path('communications/', AdminCommunicationsView.as_view(), name='communications'),

    # ── Audit Logs (legacy — keep working) ─────────────────────────────────
    path('audit-logs/', AdminAuditLogsView.as_view(), name='audit_logs'),

    # ── Platform Settings ────────────────────────────────────────────────────
    path('settings/platform/', AdminPlatformSettingsView.as_view(), name='platform_settings'),
    path('settings/site/', AdminSiteSettingsView.as_view(), name='site_settings'),
]


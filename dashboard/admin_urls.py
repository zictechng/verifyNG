from django.urls import path
from dashboard.admin_views import (
    # Existing
    AdminOverviewView,
    AdminSubscriptionActionView,
    AdminUserListView,
    AdminUserToggleStatusView,
    AdminUserChangeRoleView,
    AdminAuditLogsView,
    AdminCommunicationsView,
    # Users — extended
    AdminUserDetailView,
    AdminUserActivityExportView,
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
    AdminEmployerDetailView,
    AdminEmployerActivityExportView,
    # Subscriptions
    AdminSubscriptionsView,
    # Analytics
    AdminAnalyticsView,
    # System Logs
    AdminSystemLogsView,
    AdminActivityLogsView,
    AdminLoginLogsView,
    # Platform Settings
    AdminPlatformSettingsView,
    AdminSiteSettingsView,

    AdminCreateUserView,
    AdminUserServiceAccessView,
    AdminPlansView,
    AdminPlanCreateEditView,
    AdminCreditSubscriptionView,
    AdminCertificatesView,
    AdminCertificateActionView,
    AdminDisputeDetailView,
    AdminNotificationsView,
    AdminVerificationDetailView,
)

app_name = 'admin_portal'

urlpatterns = [
    # ── Overview Dashboard ─────────────────────────────────────────────────
    path('', AdminOverviewView.as_view(), name='overview'),

    # ── Analytics ─────────────────────────────────────────────────────────
    path('analytics/', AdminAnalyticsView.as_view(), name='analytics'),

    # ── User Management ────────────────────────────────────────────────────
    path('users/', AdminUserListView.as_view(), name='users'),
    path('users/<uuid:public_id>/', AdminUserDetailView.as_view(), name='user_detail'),
    path('users/<uuid:public_id>/toggle-status/', AdminUserToggleStatusView.as_view(), name='user_toggle_status'),
    path('users/<uuid:public_id>/change-role/', AdminUserChangeRoleView.as_view(), name='user_change_role'),
    path('users/<uuid:public_id>/block/', AdminUserBlockView.as_view(), name='user_block'),
    path('users/<uuid:public_id>/hard-delete/', AdminUserHardDeleteView.as_view(), name='user_hard_delete'),
    path('users/<uuid:public_id>/export/', AdminUserActivityExportView.as_view(), name='user_activity_export'),

        # ── User Creation ────────────────────────────────────────────────────────
    path('users/create/', AdminCreateUserView.as_view(), name='user_create'),

    # ── Per-user service access ──────────────────────────────────────────────
    path('users/<uuid:public_id>/service-access/', AdminUserServiceAccessView.as_view(), name='user_service_access'),

    # ── Reports Moderation ─────────────────────────────────────────────────
    path('reports/', AdminReportsView.as_view(), name='reports'),
    path('reports/<int:pk>/', AdminReportDetailView.as_view(), name='report_detail'),
    path('reports/<int:pk>/transition/', AdminReportTransitionView.as_view(), name='report_transition'),

    # ── Disputes ────────────────────────────────────────────────────────────
    path('disputes/', AdminDisputesView.as_view(), name='disputes'),
    path('disputes/<int:pk>/action/', AdminDisputeActionView.as_view(), name='dispute_action'),
    path('disputes/<int:pk>/', AdminDisputeDetailView.as_view(), name='dispute_detail'),

    # ── Verifications ───────────────────────────────────────────────────────
    path('verifications/', AdminVerificationsView.as_view(), name='verifications'),
    path('verifications/<int:pk>/action/', AdminVerificationActionView.as_view(), name='verification_action'),
    path('verifications/<int:pk>/', AdminVerificationDetailView.as_view(), name='verification_detail'),

    # ── Employer Profiles ───────────────────────────────────────────────────
    path('employers/', AdminEmployerProfilesView.as_view(), name='employer_profiles'),
    path('employers/<int:pk>/action/', AdminEmployerActionView.as_view(), name='employer_action'),
    path('employers/<int:pk>/', AdminEmployerDetailView.as_view(), name='employer_detail'),
    path('employers/<int:pk>/export/', AdminEmployerActivityExportView.as_view(), name='employer_activity_export'),

    # ── Subscriptions / Payments ────────────────────────────────────────────
    path('subscriptions/', AdminSubscriptionsView.as_view(), name='subscriptions'),
    path('subscriptions/<uuid:pk>/action/', AdminSubscriptionActionView.as_view(), name='subscription_action'),
    path('plans/', AdminPlansView.as_view(), name='plans'),
    path('plans/new/', AdminPlanCreateEditView.as_view(), name='plan_create'),
    path('plans/<int:pk>/edit/', AdminPlanCreateEditView.as_view(), name='plan_edit'),
    path('users/<uuid:public_id>/credit-subscription/', AdminCreditSubscriptionView.as_view(), name='credit_subscription'),

    # ── Logs ────────────────────────────────────────────────────────────────
    path('logs/system/', AdminSystemLogsView.as_view(), name='system_logs'),
    path('logs/activity/', AdminActivityLogsView.as_view(), name='activity_logs'),
    path('logs/login/', AdminLoginLogsView.as_view(), name='login_logs'),
    path('notifications/', AdminNotificationsView.as_view(), name='notifications'),
    # ── Communications ──────────────────────────────────────────────────────

    path('communications/', AdminCommunicationsView.as_view(), name='communications'),

    # ── Audit Logs (legacy — keep working) ─────────────────────────────────
    path('audit-logs/', AdminAuditLogsView.as_view(), name='audit_logs'),

    # ── Platform Settings ────────────────────────────────────────────────────
    path('settings/platform/', AdminPlatformSettingsView.as_view(), name='platform_settings'),
    path('settings/site/', AdminSiteSettingsView.as_view(), name='site_settings'),

    # ── Certificates ─────────────────────────────────────────────────────────
    path('certificates/', AdminCertificatesView.as_view(), name='certificates'),
    path('certificates/<int:pk>/action/', AdminCertificateActionView.as_view(), name='certificate_action'),

]


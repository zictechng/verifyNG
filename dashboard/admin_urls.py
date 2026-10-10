
from django.urls import path
from dashboard.admin_views import (
    AdminOverviewView,
    AdminUserListView,
    AdminUserToggleStatusView,
    AdminUserChangeRoleView,
    AdminAuditLogsView,
    AdminCommunicationsView,
)

app_name = 'admin_portal'

urlpatterns = [
    path('', AdminOverviewView.as_view(), name='overview'),
    path('users/', AdminUserListView.as_view(), name='users'),
    path('users/<int:user_id>/toggle-status/', AdminUserToggleStatusView.as_view(), name='user_toggle_status'),
    path('users/<int:user_id>/change-role/', AdminUserChangeRoleView.as_view(), name='user_change_role'),
    path('audit-logs/', AdminAuditLogsView.as_view(), name='audit_logs'),
    path('communications/', AdminCommunicationsView.as_view(), name='communications'),
]


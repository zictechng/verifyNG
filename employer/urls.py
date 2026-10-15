# employer/urls.py
from django.urls import path
from . import views

app_name = 'employer'

urlpatterns = [
    # Dashboard & profile
    path('', views.employer_dashboard, name='dashboard'),
    path('profile/', views.employer_profile, name='profile'),

    # Staff check requests — BATCH 1
    path('checks/', views.staff_check_list, name='staff_check_list'),
    path('checks/new/', views.staff_check_create, name='staff_check_create'),
    path('checks/<uuid:check_id>/', views.staff_check_detail, name='staff_check_detail'),
    path('checks/<uuid:check_id>/cancel/', views.staff_check_cancel, name='staff_check_cancel'),

    # Monitoring — BATCH 1
    path('monitoring/', views.monitoring_list, name='monitoring_list'),
    path('checks/<uuid:check_id>/monitor/toggle/', views.monitoring_toggle, name='monitoring_toggle'),

    # Bulk checks — BATCH 2
    path('bulk-checks/', views.bulk_upload_list, name='bulk_upload_list'),
    path('bulk-checks/upload/', views.bulk_upload_create, name='bulk_upload_create'),
    path('bulk-checks/template.csv', views.bulk_csv_template, name='bulk_csv_template'),
    path('bulk-checks/<uuid:upload_id>/', views.bulk_upload_detail, name='bulk_upload_detail'),
        # CSV Export — BATCH 8
    path('checks/export/', views.staff_check_export_csv, name='staff_check_export'),

    # Team — BATCH 3
    path('team/', views.team_list, name='team_list'),
    path('team/invite/', views.team_invite_send, name='team_invite_send'),
    path('team/<int:member_id>/remove/', views.team_member_remove, name='team_member_remove'),

    # Team invitation accept — public (no employer_required)
    path('invite/accept/<str:token>/', views.team_invite_accept, name='team_invite_accept'),

    # Person / Landlord quick-check — BATCH 4
    path('checks/person/', views.person_check_search, name='person_check_search'),
]

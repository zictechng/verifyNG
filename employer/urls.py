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

    # Team
    path('team/', views.team_list, name='team_list'),
]


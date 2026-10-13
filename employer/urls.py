
# employer/urls.py
from django.urls import path
from . import views

app_name = 'employer'

urlpatterns = [
    path('', views.employer_dashboard, name='dashboard'),
    path('profile/', views.employer_profile, name='profile'),
    path('bulk-checks/', views.bulk_upload_list, name='bulk_upload_list'),
    path('bulk-checks/<uuid:upload_id>/', views.bulk_upload_detail, name='bulk_upload_detail'),
    path('team/', views.team_list, name='team_list'),
]


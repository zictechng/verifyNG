
from django.urls import path
from verification import views

app_name = 'verification'

urlpatterns = [
    path('', views.VerificationListView.as_view(), name='list'),
    path('new/', views.VerificationCreateView.as_view(), name='create'),
    path('queue/', views.OfficerQueueView.as_view(), name='officer_queue'),
    path('<str:reference_number>/', views.VerificationDetailView.as_view(), name='detail'),
    path('<str:reference_number>/report/', views.VerificationReportDocumentView.as_view(), name='report'),
    path('<str:reference_number>/claim/', views.OfficerClaimView.as_view(), name='officer_claim'),
    path('<str:reference_number>/resolve/', views.OfficerResolveView.as_view(), name='officer_resolve'),

]


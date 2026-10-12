
from django.urls import path
from verification import views

app_name = 'verification'

urlpatterns = [
    # ── Existing verification request URLs ────────────────────────────────
    path('', views.VerificationListView.as_view(), name='list'),
    path('new/', views.VerificationCreateView.as_view(), name='create'),
    path('queue/', views.OfficerQueueView.as_view(), name='officer_queue'),
    path('<str:reference_number>/', views.VerificationDetailView.as_view(), name='detail'),
    path('<str:reference_number>/report/', views.VerificationReportDocumentView.as_view(), name='report'),
    path('<str:reference_number>/claim/', views.OfficerClaimView.as_view(), name='officer_claim'),
    path('<str:reference_number>/resolve/', views.OfficerResolveView.as_view(), name='officer_resolve'),

    # ── W-08: Certificate URLs ─────────────────────────────────────────────
    # Apply for a certificate (login required)
    path('certificate/apply/', views.CertificateApplyView.as_view(), name='certificate_apply'),

    # Holder views their own certificate dashboard (login required)
    path('certificate/mine/', views.MyCertificateView.as_view(), name='my_certificate'),

    # Holder views their query log — who checked their certificate (login required)
    path('certificate/mine/queries/', views.QueryLogView.as_view(), name='query_log'),

    # Public certificate query — login + payment required
    # This is the URL an employer enters the certificate ID into
    path('certificate/<str:certificate_id>/', views.CertificateQueryView.as_view(), name='certificate_query'),

    # PDF download — certificate holder only
    path('certificate/<str:certificate_id>/download/', views.CertificatePDFView.as_view(), name='certificate_pdf'),
]
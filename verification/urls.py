from django.urls import path
from verification import views

app_name = 'verification'

urlpatterns = [
    # ── Existing Phase 6 routes ────────────────────────────────────────
    path('', views.VerificationListView.as_view(), name='list'),
    path('new/', views.VerificationCreateView.as_view(), name='create'),
    path('queue/', views.OfficerQueueView.as_view(), name='officer_queue'),

    # ── W-08: Certificate routes (MUST precede the catch-all below) ────
    path('certificate/apply/', views.CertificateApplyView.as_view(), name='certificate_apply'),
    path('certificate/query/', views.CertificateQueryLandingView.as_view(), name='certificate_query_landing'),
    path('certificate/', views.MyCertificatesListView.as_view(), name='my_certificates'),
    path('certificate/query/result/', views.CertificateQueryResultView.as_view(), name='certificate_query_result'),
    path('certificate/<str:certificate_id>/', views.MyCertificateView.as_view(), name='my_certificate'),
    path('certificate/<str:certificate_id>/verify/', views.CertificatePublicVerifyView.as_view(), name='certificate_public_verify'),
    path('certificate/<str:certificate_id>/log/', views.CertificateQueryLogView.as_view(), name='query_log'),
    path('certificate/<str:certificate_id>/download/', views.CertificateDownloadPDFView.as_view(), name='certificate_download_pdf'),
    path('certificate/<str:certificate_id>/activate/', views.CertificateActivateView.as_view(), name='certificate_activate'),
    path('certificate/<str:certificate_id>/revoke/', views.CertificateRevokeView.as_view(), name='certificate_revoke'),

    # ── Existing catch-all (must remain LAST) ─────────────────────────
    path('<str:reference_number>/document/<int:doc_id>/', views.VerificationDocumentView.as_view(), name='document'),
    path('<str:reference_number>/document/', views.VerificationDocumentView.as_view(), name='primary_document'),
    path('<str:reference_number>/', views.VerificationDetailView.as_view(), name='detail'),
    path('<str:reference_number>/report/', views.VerificationReportDocumentView.as_view(), name='report'),
    path('<str:reference_number>/claim/', views.OfficerClaimView.as_view(), name='officer_claim'),
    path('<str:reference_number>/resolve/', views.OfficerResolveView.as_view(), name='officer_resolve'),
]


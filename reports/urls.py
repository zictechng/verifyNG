from django.urls import path
from reports.views import (
    ReportCreateView,
    ReportDetailView,
    EvidenceDownloadView,
    EvidenceUploadView,
    DisputeCreateView,
    ModerationQueueView,
    ReportModerationTransitionView,
    DisputeResolveView,
    SubjectPhotoUploadView,
)

app_name = 'reports'

urlpatterns = [
    # Specific actions registered first to avoid route shadowing
    path('submit/', ReportCreateView.as_view(), name='create'),
    path('moderation/', ModerationQueueView.as_view(), name='moderation_queue'),
    path('moderation/<str:reference_number>/transition/', ReportModerationTransitionView.as_view(), name='moderation_transition'),
    path('disputes/<int:dispute_id>/resolve/', DisputeResolveView.as_view(), name='resolve_dispute'),
    path('evidence/<int:evidence_id>/download/', EvidenceDownloadView.as_view(), name='evidence_download'),
    path('<str:reference_number>/evidence/upload/', EvidenceUploadView.as_view(), name='upload_evidence'),
    path('<str:reference_number>/subject/photo/upload/', SubjectPhotoUploadView.as_view(), name='upload_subject_photo'),
    path('<str:reference_number>/dispute/', DisputeCreateView.as_view(), name='create_dispute'),

    # Catch-all detail view registered last
    path('<str:reference_number>/', ReportDetailView.as_view(), name='detail'),
]


from django.urls import path
from reports.views import (
    ReportCreateView,
    MyReportsListView,
    MyDisputesListView,
    ReportDetailView,
    EvidenceDownloadView,
    EvidenceUploadView,
    DisputeCreateView,
    ModerationQueueView,
    ReportModerationTransitionView,
    DisputeResolveView,
    DisputeCounterEvidenceView,
    SubjectPhotoUploadView,
    RebuttalCreateView,
    ModeratorInfoRequestView,
    InfoRequestFulfillView,
)

app_name = 'reports'

urlpatterns = [
    # Specific actions registered first to avoid route shadowing
    path('submit/', ReportCreateView.as_view(), name='create'),
    path('my-reports/', MyReportsListView.as_view(), name='my_reports'),
    path('my-disputes/', MyDisputesListView.as_view(), name='my_disputes'),
    path('moderation/', ModerationQueueView.as_view(), name='moderation_queue'),
    path('moderation/<str:reference_number>/transition/', ReportModerationTransitionView.as_view(), name='moderation_transition'),
    path('disputes/<int:dispute_id>/resolve/', DisputeResolveView.as_view(), name='resolve_dispute'),
    path('disputes/<int:dispute_id>/counter-evidence/', DisputeCounterEvidenceView.as_view(), name='dispute_counter_evidence'),
    path('evidence/<int:evidence_id>/download/', EvidenceDownloadView.as_view(), name='evidence_download'),
    path('<str:reference_number>/evidence/upload/', EvidenceUploadView.as_view(), name='upload_evidence'),
    path('<str:reference_number>/subject/photo/upload/', SubjectPhotoUploadView.as_view(), name='upload_subject_photo'),
    path('<str:reference_number>/dispute/', DisputeCreateView.as_view(), name='create_dispute'),
    path('<str:reference_number>/rebuttal/', RebuttalCreateView.as_view(), name='create_rebuttal'),
    path('<str:reference_number>/info-request/', ModeratorInfoRequestView.as_view(), name='issue_info_request'),
    path('<str:reference_number>/info-request/<int:request_id>/fulfill/', InfoRequestFulfillView.as_view(), name='fulfill_info_request'),

    # Catch-all detail view registered last
    path('<str:reference_number>/', ReportDetailView.as_view(), name='detail'),
]

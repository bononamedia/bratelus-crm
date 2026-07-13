from django.urls import path
from .views import jobs_board_view, EvidenceUploadView

urlpatterns = [
    # Your standard web dashboard
    path('board/', jobs_board_view, name='jobs_board'),
    
    # The API endpoint for the mobile app
    path('api/mobile/upload-evidence/', EvidenceUploadView.as_view(), name='api_upload_evidence'),
]
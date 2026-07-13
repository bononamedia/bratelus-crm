import json
from django.shortcuts import render, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.shortcuts import redirect
from django.utils import timezone
from django.core.cache import cache

# Django REST Framework
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.parsers import MultiPartParser, FormParser
from rest_framework import status
from rest_framework.permissions import IsAuthenticated

# Local Models & Tasks
from .models import Job, JobTask, JobEvidence, JobAssignment
from .tasks import verify_photo_evidence

# Data Models for the Job Creation Panel
from organizations.models import Skill, ServiceZone, WorkerProfile
from organizations.permissions import user_can_manage_workspace, worker_profile_for_workspace
from crm.models.contacts import Account, Property

# ==========================================
# 1 - WEB DASHBOARD VIEWS
# ==========================================

@login_required
def jobs_board_view(request):
    """Renders the main dispatch UI with the map and Kanban board."""
    
    # Grab the data needed for the "+ Create Job" slide-out dropdowns
    active_org = request.active_organization
    if not user_can_manage_workspace(request.user, active_org):
        if worker_profile_for_workspace(request.user, active_org):
            return redirect('employee_profile')
        raise PermissionDenied('Only workspace admins can access dispatch.')
    
    # Protect against users who don't have an active organization yet
    if active_org:
        accounts = Account.objects.filter(organization=active_org)
        properties = Property.objects.filter(account__organization=active_org)
        skills = Skill.objects.filter(workspace=active_org)
        zones = ServiceZone.objects.filter(workspace=active_org)
        workers = WorkerProfile.objects.filter(workspaces=active_org).select_related('user')
    else:
        accounts = []
        properties = []
        skills = []
        zones = []
        workers = []

    context = {
        'accounts': accounts,
        'properties': properties,
        'skills': skills,
        'zones': zones,
        'workers': workers,
    }
    
    return render(request, 'jobs.html', context)


# ==========================================
# 2 - MOBILE API: PHOTO EVIDENCE
# ==========================================

class EvidenceUploadView(APIView):
    """
    API Endpoint for the mobile app to upload job completion photos.
    Expects a Multipart Form Data POST request.
    """
    permission_classes = [IsAuthenticated]
    parser_classes = (MultiPartParser, FormParser)

    def post(self, request, *args, **kwargs):
        active_org = getattr(request, 'active_organization', None)
        if not active_org:
            return Response({"error": "No active organization selected."}, status=status.HTTP_400_BAD_REQUEST)

        job_id = request.data.get('job_id')
        task_id = request.data.get('task_id')
        photo_file = request.FILES.get('photo')

        if not all([job_id, task_id, photo_file]):
            return Response(
                {"error": "Missing required fields: job_id, task_id, and photo are required."}, 
                status=status.HTTP_400_BAD_REQUEST
            )

        try:
            job = Job.objects.get(id=job_id, organization=active_org)
            task = JobTask.objects.get(id=task_id, job=job)

            if not request.user.is_staff and not request.user.is_superuser:
                try:
                    worker_profile = request.user.workerprofile
                except WorkerProfile.DoesNotExist:
                    return Response({"error": "Worker profile required."}, status=status.HTTP_403_FORBIDDEN)

                if not JobAssignment.objects.filter(job=job, worker=worker_profile).exists():
                    return Response({"error": "You are not assigned to this job."}, status=status.HTTP_403_FORBIDDEN)

            evidence = JobEvidence.objects.create(
                job=job,
                task=task,
                photo=photo_file,
                captured_at=timezone.now(),
                lat=0.000000,  
                lng=0.000000
            )

            verify_photo_evidence.delay(evidence.id)

            return Response({
                "message": "Photo uploaded successfully. Background verification initiated.",
                "evidence_id": evidence.id
            }, status=status.HTTP_202_ACCEPTED)

        except Job.DoesNotExist:
            return Response({"error": "Job not found."}, status=status.HTTP_404_NOT_FOUND)
        except JobTask.DoesNotExist:
            return Response({"error": "Task not found on this Job."}, status=status.HTTP_404_NOT_FOUND)
        except Exception as e:
            return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


# ==========================================
# 3 - MOBILE API: TIME TRACKING (CLOCK IN/OUT)
# ==========================================

class MobileClockInView(APIView):
    """Called when the worker taps 'Clock In' on the mobile app."""
    permission_classes = [IsAuthenticated]

    def post(self, request, job_id):
        try:
            worker_profile = request.user.workerprofile
        except WorkerProfile.DoesNotExist:
            return Response({"error": "Worker profile required."}, status=status.HTTP_403_FORBIDDEN)
        
        assignment = get_object_or_404(JobAssignment, job_id=job_id, worker=worker_profile)
        job = assignment.job

        if assignment.clocked_in_at:
            return Response({"error": "You are already clocked in to this job."}, status=status.HTTP_400_BAD_REQUEST)

        now = timezone.now()
        assignment.clocked_in_at = now
        assignment.save()

        if job.status in ['pending', 'dispatched', 'accepted', 'en_route']:
            job.status = 'in_progress'
            if not job.clocked_in_at:
                job.clocked_in_at = now
            job.save()

        return Response({
            "message": "Clock in successful.",
            "clocked_in_at": now
        }, status=status.HTTP_200_OK)


class MobileClockOutView(APIView):
    """Called when the worker taps 'Clock Out' on the mobile app."""
    permission_classes = [IsAuthenticated]

    def post(self, request, job_id):
        try:
            worker_profile = request.user.workerprofile
        except WorkerProfile.DoesNotExist:
            return Response({"error": "Worker profile required."}, status=status.HTTP_403_FORBIDDEN)
        
        assignment = get_object_or_404(JobAssignment, job_id=job_id, worker=worker_profile)
        job = assignment.job

        if not assignment.clocked_in_at:
            return Response({"error": "You must clock in first."}, status=status.HTTP_400_BAD_REQUEST)
            
        if assignment.clocked_out_at:
            return Response({"error": "You are already clocked out of this job."}, status=status.HTTP_400_BAD_REQUEST)

        now = timezone.now()
        assignment.clocked_out_at = now
        assignment.save()

        active_assignments = job.worker_assignments.filter(clocked_out_at__isnull=True)
        if not active_assignments.exists():
            job.status = 'completed'
            job.completed_at = now
            job.save()

        elapsed_time = now - assignment.clocked_in_at

        return Response({
            "message": "Clock out successful.",
            "clocked_out_at": now,
            "elapsed_seconds": elapsed_time.total_seconds()
        }, status=status.HTTP_200_OK)


# ==========================================
# 4 - MOBILE API: LIVE GPS INGESTION
# ==========================================

class TrackLocationPingView(APIView):
    """
    High-frequency endpoint hit by the mobile background tracker.
    Stores the absolute latest position in Redis memory.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        active_org = getattr(request, 'active_organization', None)
        try:
            worker_profile = request.user.workerprofile
        except WorkerProfile.DoesNotExist:
            return Response({"error": "Worker profile required."}, status=status.HTTP_403_FORBIDDEN)

        if active_org and not worker_profile.workspaces.filter(id=active_org.id).exists():
            return Response({"error": "Worker does not belong to the active organization."}, status=status.HTTP_403_FORBIDDEN)
        
        lat = request.data.get('latitude')
        lng = request.data.get('longitude')
        accuracy = request.data.get('accuracy', 0.0)

        if not lat or not lng:
            return Response({"error": "Missing latitude or longitude"}, status=status.HTTP_400_BAD_REQUEST)

        location_data = {
            "worker_id": worker_profile.id,
            "worker_name": f"{request.user.first_name} {request.user.last_name}".strip() or request.user.username,
            "latitude": float(lat),
            "longitude": float(lng),
            "accuracy": float(accuracy),
            "timestamp": timezone.now().isoformat()
        }

        # 1. Update Fast Redis Cache
        cache.set(f"live_location:{worker_profile.id}", location_data, timeout=3600)

        # 2. Append to a Redis List buffer for Celery
        redis_client = cache.client.get_client()
        redis_client.rpush("raw_gps_pings_buffer", json.dumps(location_data))

        return Response({"status": "buffered"}, status=status.HTTP_200_OK)


# ==========================================
# 5 - DASHBOARD API: MAP RADAR (READ-ONLY)
# ==========================================

class LiveFleetLocationsView(APIView):
    """
    Fetches the absolute latest cached coordinates for all active workers.
    Used by the web dashboard map to plot the moving pins.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        active_org = getattr(request, 'active_organization', None)
        if not active_org:
            return Response({"fleet": []}, status=status.HTTP_200_OK)
        if not user_can_manage_workspace(request.user, active_org):
            return Response(
                {"error": "Only workspace admins can view live fleet locations."},
                status=status.HTTP_403_FORBIDDEN,
            )

        redis_client = cache.client.get_client()
        worker_ids = WorkerProfile.objects.filter(workspaces=active_org).values_list('id', flat=True)
        
        active_workers = []
        for worker_id in worker_ids:
            raw_data = redis_client.get(f"live_location:{worker_id}")
            if raw_data:
                active_workers.append(json.loads(raw_data.decode('utf-8')))
                
        return Response({"fleet": active_workers}, status=status.HTTP_200_OK)

import json
from decimal import Decimal, InvalidOperation
from django.shortcuts import render, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.shortcuts import redirect
from django.utils import timezone
from django.core.cache import cache
from django.db import transaction

# Django REST Framework
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.parsers import MultiPartParser, FormParser
from rest_framework import status
from rest_framework.permissions import IsAuthenticated

# Local Models & Tasks
from .models import FieldEvent, FieldShift, Job, JobTask, JobEvidence, JobAssignment, JobIssue, JobIssueMedia
from .tasks import send_completion_notifications, translate_field_note, verify_photo_evidence
from .translation import note_needs_translation
from .tasks import calculate_distance

# Data Models for the Job Creation Panel
from organizations.models import Skill, ServiceZone, WorkerProfile
from organizations.permissions import user_can_manage_workspace, worker_profile_for_workspace
from crm.models.contacts import Account, Contact, Property


def _location_from_request(data):
    try:
        lat = Decimal(str(data.get('latitude')))
        lng = Decimal(str(data.get('longitude')))
        accuracy = Decimal(str(data.get('accuracy') or 0))
    except (InvalidOperation, TypeError, ValueError):
        return None
    if not (-90 <= lat <= 90 and -180 <= lng <= 180):
        return None
    return lat, lng, max(accuracy, Decimal('0'))


def _worker_for_request(request):
    active_org = getattr(request, 'active_organization', None)
    if not active_org:
        return None, None
    return active_org, worker_profile_for_workspace(request.user, active_org)


def _record_field_event(worker, workspace, event_type, location, job=None, task=None, note=''):
    lat, lng, accuracy = location
    translation_status = 'pending' if event_type == 'note_added' and note_needs_translation(note) else 'not_needed'
    event = FieldEvent.objects.create(
        workspace=workspace,
        worker=worker,
        job=job,
        task=task,
        event_type=event_type,
        lat=lat,
        lng=lng,
        accuracy=accuracy,
        note_original=note,
        note_english=note if note and translation_status == 'not_needed' else '',
        source_language='en' if note and translation_status == 'not_needed' else '',
        translation_status=translation_status,
    )
    if translation_status == 'pending':
        translate_field_note.delay(event.id)
    return event


def _active_shift(worker, workspace):
    return FieldShift.objects.filter(worker=worker, workspace=workspace, ended_at__isnull=True).first()

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
        workers = WorkerProfile.objects.filter(workspaces=active_org)
        if active_org.customer_account_id:
            workers = workers.filter(
                user__customer_accounts__account=active_org.customer_account,
                user__customer_accounts__can_work_jobs=True,
                user__customer_accounts__is_active=True,
            )
        workers = workers.select_related('user').distinct()
        contacts = Contact.objects.filter(organization=active_org).select_related('account').order_by('first_name', 'last_name')
    else:
        accounts = []
        properties = []
        skills = []
        zones = []
        workers = []
        contacts = []

    context = {
        'accounts': accounts,
        'properties': properties,
        'skills': skills,
        'zones': zones,
        'workers': workers,
        'contacts': contacts,
    }
    
    return render(request, 'jobs.html', context)


@login_required
def field_operations_view(request):
    active_org, worker = _worker_for_request(request)
    if not worker:
        raise PermissionDenied('A field-work profile is required.')
    assignments = (
        JobAssignment.objects.filter(worker=worker, job__organization=active_org)
        .exclude(job__status__in=['completed', 'canceled'])
        .select_related('job', 'job__account', 'job__property')
        .prefetch_related('job__tasks', 'job__evidence')
        .order_by('job__scheduled_start', 'job__id')
    )
    return render(request, 'field_operations.html', {
        'assignments': assignments,
        'active_shift': _active_shift(worker, active_org),
    })


@login_required
def field_job_view(request, job_id):
    active_org, worker = _worker_for_request(request)
    if not worker:
        raise PermissionDenied('A field-work profile is required.')
    assignment = get_object_or_404(
        JobAssignment.objects.select_related('job', 'job__account', 'job__property', 'worker__user'),
        worker=worker,
        job_id=job_id,
        job__organization=active_org,
    )
    return render(request, 'field_job.html', {
        'assignment': assignment,
        'job': assignment.job,
        'tasks': assignment.job.tasks.prefetch_related('evidence').all(),
        'events': assignment.job.field_events.filter(worker=worker)[:30],
        'issues': assignment.job.issues.filter(worker=worker).prefetch_related('media')[:20],
        'active_shift': _active_shift(worker, active_org),
    })


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
        active_org, worker_profile = _worker_for_request(request)
        if not active_org:
            return Response({"error": "No active organization selected."}, status=status.HTTP_400_BAD_REQUEST)
        if not worker_profile:
            return Response({"error": "Worker profile required."}, status=status.HTTP_403_FORBIDDEN)

        job_id = request.data.get('job_id')
        task_id = request.data.get('task_id')
        evidence_file = request.FILES.get('evidence') or request.FILES.get('photo')
        location = _location_from_request(request.data)

        if not all([job_id, evidence_file, location]):
            return Response(
                {"error": "Job, media file, and current location are required."},
                status=status.HTTP_400_BAD_REQUEST
            )

        try:
            job = Job.objects.get(id=job_id, organization=active_org)
            task = JobTask.objects.filter(id=task_id, job=job).first() if task_id else None

            if not JobAssignment.objects.filter(job=job, worker=worker_profile).exists():
                return Response({"error": "You are not assigned to this job."}, status=status.HTTP_403_FORBIDDEN)

            content_type = (getattr(evidence_file, 'content_type', '') or '').lower()
            media_type = 'video' if content_type.startswith('video/') else 'photo'
            if not (content_type.startswith('image/') or content_type.startswith('video/')):
                return Response({"error": "Only photo and video evidence is supported."}, status=status.HTTP_400_BAD_REQUEST)
            if evidence_file.size > 100 * 1024 * 1024:
                return Response({"error": "Evidence files must be 100 MB or smaller."}, status=status.HTTP_400_BAD_REQUEST)

            lat, lng, _ = location
            evidence = JobEvidence.objects.create(
                job=job,
                task=task,
                photo=evidence_file,
                media_type=media_type,
                uploaded_by=worker_profile,
                note=request.data.get('note', '').strip(),
                captured_at=timezone.now(),
                lat=lat,
                lng=lng,
            )
            _record_field_event(worker_profile, active_org, 'evidence_added', location, job=job, task=task, note=evidence.note)
            if media_type == 'photo':
                verify_photo_evidence.delay(evidence.id)
            else:
                evidence.is_verified = True
                evidence.qc_notes = 'Video location captured by the field workflow.'
                evidence.save(update_fields=['is_verified', 'qc_notes'])

            return Response({
                "message": "Photo uploaded successfully. Background verification initiated.",
                "evidence_id": evidence.id
            }, status=status.HTTP_202_ACCEPTED)

        except Job.DoesNotExist:
            return Response({"error": "Job not found."}, status=status.HTTP_404_NOT_FOUND)
        except Exception as e:
            return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class FieldShiftView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        workspace, worker = _worker_for_request(request)
        location = _location_from_request(request.data)
        if not worker:
            return Response({'error': 'Field-work profile required.'}, status=status.HTTP_403_FORBIDDEN)
        if not location:
            return Response({'error': 'Precise location access is required.'}, status=status.HTTP_400_BAD_REQUEST)
        action = request.data.get('action')
        shift = _active_shift(worker, workspace)
        if action == 'start':
            if shift:
                return Response({'error': 'You are already available for work.'}, status=status.HTTP_400_BAD_REQUEST)
            lat, lng, _ = location
            shift = FieldShift.objects.create(worker=worker, workspace=workspace, start_lat=lat, start_lng=lng)
            _record_field_event(worker, workspace, 'shift_started', location)
            return Response({'message': 'You are checked in and available for dispatch.', 'shift_id': shift.id})
        if action == 'end':
            if not shift:
                return Response({'error': 'No active field shift was found.'}, status=status.HTTP_400_BAD_REQUEST)
            if JobAssignment.objects.filter(worker=worker, clocked_in_at__isnull=False, clocked_out_at__isnull=True).exists():
                return Response({'error': 'Close your active job before ending the shift.'}, status=status.HTTP_400_BAD_REQUEST)
            lat, lng, _ = location
            shift.ended_at = timezone.now()
            shift.end_lat = lat
            shift.end_lng = lng
            shift.save(update_fields=['ended_at', 'end_lat', 'end_lng'])
            _record_field_event(worker, workspace, 'shift_ended', location)
            return Response({'message': 'Field shift ended.'})
        return Response({'error': 'Choose start or end.'}, status=status.HTTP_400_BAD_REQUEST)


class FieldIssueReportView(APIView):
    permission_classes = [IsAuthenticated]
    parser_classes = (MultiPartParser, FormParser)

    @transaction.atomic
    def post(self, request, job_id):
        workspace, worker = _worker_for_request(request)
        location = _location_from_request(request.data)
        if not worker:
            return Response({'error': 'Field-work profile required.'}, status=status.HTTP_403_FORBIDDEN)
        if not location:
            return Response({'error': 'Location is required to report a problem.'}, status=status.HTTP_400_BAD_REQUEST)
        if not _active_shift(worker, workspace):
            return Response({'error': 'Check in before reporting a field problem.'}, status=status.HTTP_400_BAD_REQUEST)
        assignment = get_object_or_404(
            JobAssignment.objects.select_related('job'),
            worker=worker,
            job_id=job_id,
            job__organization=workspace,
        )
        title = request.data.get('title', '').strip()
        description = request.data.get('description', '').strip()
        transcript = request.data.get('voice_transcript', '').strip()
        priority = request.data.get('priority', 'normal')
        if not title:
            return Response({'error': 'Problem title is required.'}, status=status.HTTP_400_BAD_REQUEST)
        if not description and not transcript:
            return Response({'error': 'Add a description or voice transcript.'}, status=status.HTTP_400_BAD_REQUEST)
        if priority not in dict(JobIssue.PRIORITY_CHOICES):
            priority = 'normal'

        media_files = request.FILES.getlist('media')
        if len(media_files) > 10:
            return Response({'error': 'Attach no more than 10 files per report.'}, status=status.HTTP_400_BAD_REQUEST)
        validated_media = []
        for upload in media_files:
            content_type = (getattr(upload, 'content_type', '') or '').lower()
            if upload.size > 100 * 1024 * 1024:
                return Response({'error': f'{upload.name} is larger than 100 MB.'}, status=status.HTTP_400_BAD_REQUEST)
            if content_type.startswith('image/'):
                media_type = 'photo'
            elif content_type.startswith('video/'):
                media_type = 'video'
            elif content_type.startswith('audio/'):
                media_type = 'audio'
            else:
                return Response({'error': f'{upload.name} is not a supported photo, video, or audio file.'}, status=status.HTTP_400_BAD_REQUEST)
            validated_media.append((upload, media_type))

        lat, lng, accuracy = location
        issue = JobIssue.objects.create(
            workspace=workspace,
            job=assignment.job,
            worker=worker,
            assignment=assignment,
            title=title[:180],
            description=description,
            voice_transcript=transcript,
            priority=priority,
            lat=lat,
            lng=lng,
            accuracy=accuracy,
        )
        for upload, media_type in validated_media:
            JobIssueMedia.objects.create(issue=issue, file=upload, media_type=media_type)

        _record_field_event(
            worker,
            workspace,
            'problem_reported',
            location,
            job=assignment.job,
            note=title,
        )
        return Response({
            'message': 'Problem reported to dispatch.',
            'issue_id': issue.id,
            'account_id': assignment.job.account_id,
            'property_id': assignment.job.property_id,
        }, status=status.HTTP_201_CREATED)


class FieldIssueStatusView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, issue_id):
        workspace = getattr(request, 'active_organization', None)
        if not user_can_manage_workspace(request.user, workspace):
            return Response({'error': 'Manager access required.'}, status=status.HTTP_403_FORBIDDEN)
        issue = get_object_or_404(JobIssue, id=issue_id, workspace=workspace)
        new_status = request.data.get('status')
        if new_status not in {'acknowledged', 'resolved'}:
            return Response({'error': 'Choose acknowledged or resolved.'}, status=status.HTTP_400_BAD_REQUEST)
        issue.status = new_status
        if new_status == 'acknowledged':
            issue.acknowledged_at = timezone.now()
            update_fields = ['status', 'acknowledged_at']
        else:
            issue.resolved_at = timezone.now()
            issue.resolution_notes = request.data.get('resolution_notes', '').strip()
            update_fields = ['status', 'resolved_at', 'resolution_notes']
        issue.save(update_fields=update_fields)
        return Response({'message': f'Problem marked {new_status}.', 'status': issue.status})


class FieldJobActionView(APIView):
    permission_classes = [IsAuthenticated]

    @transaction.atomic
    def post(self, request, job_id):
        workspace, worker = _worker_for_request(request)
        location = _location_from_request(request.data)
        if not worker:
            return Response({'error': 'Field-work profile required.'}, status=status.HTTP_403_FORBIDDEN)
        if not location:
            return Response({'error': 'Location must be enabled to continue.'}, status=status.HTTP_400_BAD_REQUEST)
        assignment = get_object_or_404(
            JobAssignment.objects.select_for_update().select_related('job'),
            worker=worker,
            job_id=job_id,
            job__organization=workspace,
        )
        job = assignment.job
        action = request.data.get('action')
        now = timezone.now()

        if job.status in {'completed', 'canceled'}:
            return Response({'error': 'This job is already closed.'}, status=status.HTTP_400_BAD_REQUEST)
        if not _active_shift(worker, workspace):
            return Response({'error': 'Check in as available before working a job.'}, status=status.HTTP_400_BAD_REQUEST)

        if action == 'accept':
            if not assignment.accepted_at:
                assignment.accepted_at = now
                assignment.save(update_fields=['accepted_at'])
            if job.status == 'dispatched':
                job.status = 'accepted'
                job.save(update_fields=['status'])
            _record_field_event(worker, workspace, 'job_accepted', location, job=job)
            return Response({'message': 'Job accepted.'})

        if not assignment.accepted_at:
            return Response({'error': 'Accept the job first.'}, status=status.HTTP_400_BAD_REQUEST)

        if action == 'arrive':
            expected_lat = job.location_lat or (job.property.location_lat if job.property else None)
            expected_lng = job.location_lng or (job.property.location_lng if job.property else None)
            if job.require_location and expected_lat is not None and expected_lng is not None:
                distance = calculate_distance(float(location[0]), float(location[1]), float(expected_lat), float(expected_lng))
                if distance > job.arrival_radius_meters:
                    return Response({'error': f'You are approximately {int(distance)} meters from the job. Move within {job.arrival_radius_meters} meters to arrive.'}, status=status.HTTP_400_BAD_REQUEST)
            assignment.arrived_at = assignment.arrived_at or now
            assignment.save(update_fields=['arrived_at'])
            _record_field_event(worker, workspace, 'arrived', location, job=job)
            return Response({'message': 'Arrival recorded.'})

        if not assignment.arrived_at:
            return Response({'error': 'Record arrival before starting work.'}, status=status.HTTP_400_BAD_REQUEST)

        if action == 'start_work':
            if not assignment.clocked_in_at:
                assignment.clocked_in_at = now
                assignment.save(update_fields=['clocked_in_at'])
            job.status = 'in_progress'
            job.clocked_in_at = job.clocked_in_at or now
            job.save(update_fields=['status', 'clocked_in_at'])
            _record_field_event(worker, workspace, 'work_started', location, job=job)
            return Response({'message': 'Work timer started.'})

        if not assignment.clocked_in_at:
            return Response({'error': 'Start work before updating the project.'}, status=status.HTTP_400_BAD_REQUEST)

        if action == 'add_note':
            note = request.data.get('note', '').strip()
            if not note:
                return Response({'error': 'Enter a note first.'}, status=status.HTTP_400_BAD_REQUEST)
            event = _record_field_event(worker, workspace, 'note_added', location, job=job, note=note)
            return Response({'message': 'Note saved.', 'translation_status': event.translation_status})

        if action == 'complete_task':
            if job.completion_mode != 'tasks':
                return Response({'error': 'This job is configured for whole-project completion.'}, status=status.HTTP_400_BAD_REQUEST)
            task = get_object_or_404(JobTask.objects.select_for_update(), id=request.data.get('task_id'), job=job)
            if task.requires_evidence and not task.evidence.exists():
                return Response({'error': 'Upload required photo or video evidence before completing this task.'}, status=status.HTTP_400_BAD_REQUEST)
            task.is_completed = True
            task.completed_at = now
            task.completed_by = worker
            task.completion_notes = request.data.get('note', '').strip()
            task.save(update_fields=['is_completed', 'completed_at', 'completed_by', 'completion_notes'])
            _record_field_event(worker, workspace, 'task_completed', location, job=job, task=task, note=task.completion_notes)
            if not job.tasks.filter(is_completed=False).exists():
                assignment.work_completed_at = now
                assignment.save(update_fields=['work_completed_at'])
            return Response({'message': 'Task completed.', 'work_complete': bool(assignment.work_completed_at)})

        if action == 'complete_work':
            if job.completion_mode == 'tasks' and job.tasks.exists():
                return Response({'error': 'Complete each required task for this job.'}, status=status.HTTP_400_BAD_REQUEST)
            missing_evidence = job.tasks.filter(requires_evidence=True).exclude(evidence__isnull=False).exists()
            if missing_evidence:
                return Response({'error': 'Upload evidence for every required task before completing the project.'}, status=status.HTTP_400_BAD_REQUEST)
            job.tasks.update(is_completed=True, completed_at=now, completed_by=worker)
            assignment.work_completed_at = now
            assignment.save(update_fields=['work_completed_at'])
            _record_field_event(worker, workspace, 'task_completed', location, job=job, note=request.data.get('note', '').strip())
            return Response({'message': 'Project work marked complete. Perform the closeout step next.'})

        if action == 'close_job':
            if not assignment.work_completed_at:
                return Response({'error': 'Complete the required work before closeout.'}, status=status.HTTP_400_BAD_REQUEST)
            if job.require_closeout_confirmation and request.data.get('confirmed') not in [True, 'true', '1', 1, 'yes']:
                return Response({'error': 'Confirm the closeout instruction before closing the job.'}, status=status.HTTP_400_BAD_REQUEST)
            assignment.closeout_confirmed_at = now
            assignment.clocked_out_at = now
            assignment.save(update_fields=['closeout_confirmed_at', 'clocked_out_at'])
            _record_field_event(worker, workspace, 'closeout_confirmed', location, job=job, note=request.data.get('note', '').strip())
            if assignment.is_primary_worker or not job.worker_assignments.exclude(id=assignment.id).exists():
                job.status = 'completed'
                job.completed_at = now
                if job.completion_notification_method != 'none' and not job.completion_notification_queued_at:
                    job.completion_notification_queued_at = now
                job.save(update_fields=['status', 'completed_at', 'completion_notification_queued_at'])
                _record_field_event(worker, workspace, 'job_completed', location, job=job)
                if job.completion_notification_method != 'none':
                    transaction.on_commit(lambda: send_completion_notifications.delay(job.id))
            return Response({'message': 'Job closed. Your next assignment is ready.', 'job_completed': job.status == 'completed'})

        return Response({'error': 'Unknown field action.'}, status=status.HTTP_400_BAD_REQUEST)


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
        
        location = _location_from_request(request.data)
        if not location:
            return Response({"error": "Location is required. Use the field workflow to start work."}, status=status.HTTP_400_BAD_REQUEST)
        assignment = get_object_or_404(JobAssignment, job_id=job_id, worker=worker_profile)
        job = assignment.job

        if not _active_shift(worker_profile, job.organization):
            return Response({"error": "Check in as available first."}, status=status.HTTP_400_BAD_REQUEST)
        if not assignment.accepted_at or not assignment.arrived_at:
            return Response({"error": "Accept the job and record arrival before clocking in."}, status=status.HTTP_400_BAD_REQUEST)

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
        
        location = _location_from_request(request.data)
        if not location:
            return Response({"error": "Location is required. Use the field workflow to close the job."}, status=status.HTTP_400_BAD_REQUEST)
        assignment = get_object_or_404(JobAssignment, job_id=job_id, worker=worker_profile)
        job = assignment.job

        if not assignment.clocked_in_at:
            return Response({"error": "You must clock in first."}, status=status.HTTP_400_BAD_REQUEST)
            
        if assignment.clocked_out_at:
            return Response({"error": "You are already clocked out of this job."}, status=status.HTTP_400_BAD_REQUEST)
        if not assignment.work_completed_at or not assignment.closeout_confirmed_at:
            return Response({"error": "Complete the work and closeout confirmation before clocking out."}, status=status.HTTP_400_BAD_REQUEST)

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

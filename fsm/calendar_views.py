import json
from datetime import timedelta

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, render
from django.utils.dateparse import parse_datetime
from django.views.decorators.http import require_GET, require_http_methods

from crm.models.contacts import Account, Property
from organizations.models import WorkerProfile, Workspace
from organizations.permissions import account_workspaces_for_user, user_can_manage_workspace

from .models import Job, JobAssignment


def _visible_workspaces(request):
    return account_workspaces_for_user(request.user, getattr(request, 'active_organization', None))


def _requested_workspaces(request):
    visible = _visible_workspaces(request)
    raw_ids = request.GET.get('workspaces', '')
    if not raw_ids:
        return visible
    ids = [item for item in raw_ids.split(',') if item]
    return visible.filter(id__in=ids)


@login_required
def job_calendar_view(request):
    active = getattr(request, 'active_organization', None)
    if not user_can_manage_workspace(request.user, active):
        raise PermissionDenied('Calendar access requires an office role.')
    return render(request, 'job_calendar.html', {
        'calendar_workspaces': _visible_workspaces(request).order_by('name'),
    })


@login_required
@require_GET
def calendar_options_view(request):
    workspaces = list(_visible_workspaces(request).order_by('name'))
    workspace_ids = [workspace.id for workspace in workspaces]
    accounts = Account.objects.filter(organization_id__in=workspace_ids).order_by('name')
    properties = Property.objects.filter(account__organization_id__in=workspace_ids).select_related('account').order_by('name')
    worker_filters = {'workspaces__id__in': workspace_ids}
    customer_account = getattr(getattr(request, 'active_organization', None), 'customer_account', None)
    if customer_account:
        worker_filters.update({
            'user__customer_accounts__account': customer_account,
            'user__customer_accounts__can_work_jobs': True,
            'user__customer_accounts__is_active': True,
        })
    workers = WorkerProfile.objects.filter(**worker_filters).select_related('user').distinct().order_by(
        'user__first_name', 'user__last_name', 'user__username'
    )
    return JsonResponse({
        'workspaces': [
            {'id': str(item.id), 'name': item.name, 'color': item.calendar_color}
            for item in workspaces
        ],
        'accounts': [
            {'id': item.id, 'workspace_id': str(item.organization_id), 'name': item.name}
            for item in accounts
        ],
        'properties': [
            {
                'id': item.id,
                'workspace_id': str(item.account.organization_id),
                'account_id': item.account_id,
                'name': item.name,
                'address': item.address,
            }
            for item in properties
        ],
        'workers': [
            {
                'id': item.id,
                'name': item.user.get_full_name() or item.user.username,
                'workspace_ids': [str(value) for value in item.workspaces.filter(id__in=workspace_ids).values_list('id', flat=True)],
            }
            for item in workers
        ],
    })


@login_required
@require_http_methods(['GET', 'POST'])
def calendar_jobs_view(request):
    if request.method == 'GET':
        workspaces = _requested_workspaces(request)
        jobs = Job.objects.filter(organization__in=workspaces).select_related(
            'organization', 'account', 'property'
        ).prefetch_related('worker_assignments__worker__user')
        start = parse_datetime(request.GET.get('start', ''))
        end = parse_datetime(request.GET.get('end', ''))
        if start:
            jobs = jobs.filter(scheduled_start__gte=start)
        if end:
            jobs = jobs.filter(scheduled_start__lt=end)
        events = []
        for job in jobs.exclude(scheduled_start__isnull=True):
            names = [
                assignment.worker.user.get_full_name() or assignment.worker.user.username
                for assignment in job.worker_assignments.all()
            ]
            events.append({
                'id': str(job.id),
                'title': job.title,
                'start': job.scheduled_start.isoformat(),
                'end': (job.scheduled_start + timedelta(minutes=job.estimated_duration_minutes)).isoformat(),
                'backgroundColor': job.organization.calendar_color,
                'borderColor': job.organization.calendar_color,
                'extendedProps': {
                    'workspace': job.organization.name,
                    'workspace_id': str(job.organization_id),
                    'account': job.account.name,
                    'property': job.property.name if job.property else '',
                    'address': (job.property.address if job.property else job.location_address),
                    'workers': names,
                    'status': job.get_status_display(),
                },
            })
        return JsonResponse(events, safe=False)

    data = json.loads(request.body or '{}')
    workspace = get_object_or_404(_visible_workspaces(request), id=data.get('workspace_id'))
    if not user_can_manage_workspace(request.user, workspace):
        raise PermissionDenied('You cannot schedule jobs in this workspace.')
    account = get_object_or_404(Account, id=data.get('account_id'), organization=workspace)
    property_obj = None
    if data.get('property_id'):
        property_obj = get_object_or_404(Property, id=data['property_id'], account=account)
    start = parse_datetime(data.get('scheduled_start', ''))
    if not start:
        return JsonResponse({'error': 'Choose a valid start date and time.'}, status=400)
    try:
        duration = max(15, min(int(data.get('duration_minutes', 60)), 1440))
    except (TypeError, ValueError):
        duration = 60
    worker_ids = data.get('worker_ids') or []
    workers = list(WorkerProfile.objects.filter(id__in=worker_ids, workspaces=workspace).select_related('user').distinct())
    title = str(data.get('title', '')).strip()
    if not title:
        return JsonResponse({'error': 'Job title is required.'}, status=400)
    with transaction.atomic():
        job = Job.objects.create(
            organization=workspace,
            account=account,
            property=property_obj,
            title=title[:255],
            description=str(data.get('description', '')).strip(),
            scheduled_start=start,
            estimated_duration_minutes=duration,
            job_type='scheduled',
            status='dispatched' if workers else 'pending',
        )
        for index, worker in enumerate(workers):
            JobAssignment.objects.create(job=job, worker=worker, is_primary_worker=index == 0)
    return JsonResponse({'id': job.id, 'message': 'Job added to the calendar.'}, status=201)


@login_required
@require_http_methods(['PATCH'])
def calendar_job_update_view(request, job_id):
    job = get_object_or_404(Job.objects.select_related('organization'), id=job_id, organization__in=_visible_workspaces(request))
    if not user_can_manage_workspace(request.user, job.organization):
        raise PermissionDenied('You cannot reschedule this job.')
    data = json.loads(request.body or '{}')
    start = parse_datetime(data.get('start', ''))
    end = parse_datetime(data.get('end', '')) if data.get('end') else None
    if not start:
        return JsonResponse({'error': 'A valid start time is required.'}, status=400)
    job.scheduled_start = start
    fields = ['scheduled_start']
    if end and end > start:
        job.estimated_duration_minutes = max(15, round((end - start).total_seconds() / 60))
        fields.append('estimated_duration_minutes')
    job.save(update_fields=fields)
    return JsonResponse({'message': 'Job rescheduled.'})

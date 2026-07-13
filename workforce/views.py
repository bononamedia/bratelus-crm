from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.shortcuts import redirect, render

from fsm.models import JobAssignment
from organizations.models import Skill, ServiceZone, WorkerProfile, WorkspaceMember
from organizations.permissions import user_can_manage_workspace, worker_profile_for_workspace


@login_required
def workforce_view(request):
    active_org = getattr(request, 'active_organization', None)
    if not user_can_manage_workspace(request.user, active_org):
        if worker_profile_for_workspace(request.user, active_org):
            return redirect('employee_profile')
        raise PermissionDenied('Only workspace admins can access Workforce.')

    if active_org:
        workers = WorkerProfile.objects.filter(workspaces=active_org).select_related('user').order_by(
            'user__first_name',
            'user__last_name',
            'user__username',
        )
        members = WorkspaceMember.objects.filter(workspace=active_org, is_active=True).select_related('user')
        active_assignments = JobAssignment.objects.filter(
            worker__workspaces=active_org,
            job__organization=active_org,
        ).exclude(job__status__in=['completed', 'canceled'])
        skills = Skill.objects.filter(workspace=active_org)
        zones = ServiceZone.objects.filter(workspace=active_org)
    else:
        workers = WorkerProfile.objects.none()
        members = WorkspaceMember.objects.none()
        active_assignments = JobAssignment.objects.none()
        skills = Skill.objects.none()
        zones = ServiceZone.objects.none()

    context = {
        'workers': workers,
        'workforce_stats': {
            'workers': workers.count(),
            'members': members.count(),
            'active_assignments': active_assignments.count(),
            'skills': skills.count(),
            'zones': zones.count(),
        },
    }
    return render(request, 'workforce.html', context)

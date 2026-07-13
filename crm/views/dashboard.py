from django.shortcuts import render
from django.contrib.auth.decorators import login_required
from fsm.models import Job, JobAssignment
from crm.models import Contact
from organizations.permissions import user_can_manage_workspace, worker_profile_for_workspace

@login_required
def dashboard_view(request):
    active_org = getattr(request, 'active_organization', None)
    can_manage = user_can_manage_workspace(request.user, active_org)
    worker_profile = worker_profile_for_workspace(request.user, active_org)

    if active_org:
        active_jobs_count = Job.objects.filter(organization=active_org, status='pending').count()
        new_leads_count = Contact.objects.filter(account__organization=active_org).count()
    else:
        active_jobs_count = 0
        new_leads_count = 0

    my_assignments = JobAssignment.objects.none()
    if active_org and worker_profile:
        my_assignments = (
            JobAssignment.objects.filter(worker=worker_profile, job__organization=active_org)
            .select_related('job', 'job__account', 'job__property')
            .order_by('-job__scheduled_start', '-job__id')
        )
    
    context = {
        'active_jobs': active_jobs_count,
        'new_leads': new_leads_count,
        'can_manage_dashboard': can_manage,
        'worker_profile': worker_profile,
        'my_open_assignments': my_assignments.exclude(job__status__in=['completed', 'canceled'])[:5],
        'my_open_jobs_count': my_assignments.exclude(job__status__in=['completed', 'canceled']).count(),
        'my_clocked_in_count': my_assignments.filter(
            clocked_in_at__isnull=False,
            clocked_out_at__isnull=True,
        ).count(),
    }
    return render(request, 'dashboard.html', context)

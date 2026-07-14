from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.shortcuts import redirect, render

from fsm.models import JobAssignment
from organizations.models import CustomerAccountMember, Skill, ServiceZone, WorkerProfile, WorkspaceMember
from organizations.permissions import (
    account_workspaces_for_user,
    customer_account_membership_for_user,
    user_can_manage_people,
    worker_profile_for_workspace,
)


@login_required
def workforce_view(request):
    active_org = getattr(request, 'active_organization', None)
    if not user_can_manage_people(request.user, active_org):
        if worker_profile_for_workspace(request.user, active_org):
            return redirect('employee_profile')
        raise PermissionDenied('Only workspace admins can access Workforce.')

    customer_account = getattr(active_org, 'customer_account', None)
    account_membership = customer_account_membership_for_user(request.user, customer_account)
    can_manage_account_team = request.user.is_superuser or bool(
        account_membership and account_membership.role in ('owner', 'admin')
    )
    account_workspaces = account_workspaces_for_user(request.user, active_org).order_by('name')

    if request.method == 'POST':
        if not can_manage_account_team:
            raise PermissionDenied('Only the account owner or an account administrator can change account-wide access.')
        target = CustomerAccountMember.objects.filter(
            id=request.POST.get('account_member_id'),
            account=customer_account,
        ).select_related('user').first()
        if not target:
            messages.error(request, 'Choose a valid account team member.')
            return redirect('workforce')
        if target.role == 'owner' and target.user_id != request.user.id:
            messages.error(request, 'The account owner access cannot be changed here.')
            return redirect('workforce')
        role = request.POST.get('role', target.role)
        if role not in dict(CustomerAccountMember.ROLE_CHOICES):
            role = target.role
        if role == 'owner' and target.user_id != customer_account.owner_id:
            role = 'admin'
        selected_ids = set(request.POST.getlist('workspace_ids'))
        allowed_ids = {str(workspace.id) for workspace in customer_account.workspaces.all()}
        selected_ids &= allowed_ids
        can_work_jobs = request.POST.get('can_work_jobs') == 'yes'

        with transaction.atomic():
            target.role = role
            target.can_work_jobs = can_work_jobs
            target.can_view_billing = request.POST.get('can_view_billing') == 'yes'
            target.save(update_fields=['role', 'can_work_jobs', 'can_view_billing'])
            workspace_role = {'owner': 'admin', 'admin': 'admin', 'manager': 'manager', 'employee': 'employee'}[role]
            for workspace in customer_account.workspaces.all():
                if str(workspace.id) in selected_ids:
                    WorkspaceMember.objects.update_or_create(
                        workspace=workspace,
                        user=target.user,
                        defaults={
                            'role': workspace_role,
                            'is_active': True,
                            'can_view_billing': target.can_view_billing,
                        },
                    )
                elif target.role != 'owner':
                    WorkspaceMember.objects.filter(workspace=workspace, user=target.user).delete()
            if can_work_jobs:
                worker, _ = WorkerProfile.objects.get_or_create(user=target.user)
                worker.workspaces.remove(*customer_account.workspaces.all())
                worker.workspaces.add(*customer_account.workspaces.filter(id__in=selected_ids))
            else:
                worker = WorkerProfile.objects.filter(user=target.user).first()
                if worker:
                    worker.workspaces.remove(*customer_account.workspaces.all())
        messages.success(request, f'Access updated for {target.user.get_full_name() or target.user.username}.')
        return redirect('workforce')

    if active_org:
        account_members = CustomerAccountMember.objects.filter(
            account=customer_account,
            is_active=True,
        ).select_related('user').prefetch_related('user__workspaces__workspace').order_by(
            'user__first_name',
            'user__last_name',
            'user__username',
        )
        workers = WorkerProfile.objects.filter(user_id__in=account_members.values('user_id')).select_related('user')
        active_assignments = JobAssignment.objects.filter(
            job__organization__in=account_workspaces,
        ).exclude(job__status__in=['completed', 'canceled'])
        skills = Skill.objects.filter(workspace__in=account_workspaces)
        zones = ServiceZone.objects.filter(workspace__in=account_workspaces)
    else:
        account_members = CustomerAccountMember.objects.none()
        workers = WorkerProfile.objects.none()
        active_assignments = JobAssignment.objects.none()
        skills = Skill.objects.none()
        zones = ServiceZone.objects.none()

    account_members = list(account_members)
    for member in account_members:
        member.assigned_workspace_ids = {
            str(workspace_member.workspace_id)
            for workspace_member in member.user.workspaces.all()
            if workspace_member.is_active
        }

    context = {
        'workers': workers,
        'account_members': account_members,
        'account_workspaces': account_workspaces,
        'customer_account': customer_account,
        'can_manage_account_team': can_manage_account_team,
        'workforce_stats': {
            'workers': workers.count(),
            'members': len(account_members),
            'active_assignments': active_assignments.count(),
            'skills': skills.count(),
            'zones': zones.count(),
        },
    }
    return render(request, 'workforce.html', context)

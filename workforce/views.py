import mimetypes

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.http import FileResponse, Http404
from django.db import transaction
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.dateparse import parse_date

from fsm.models import JobAssignment, WorkActivity
from organizations.models import (
    CustomerAccountMember,
    EmployeeDocument,
    EmployeeDocumentRequirement,
    Skill,
    ServiceZone,
    WorkerProfile,
    WorkerSkill,
    WorkspaceMember,
)
from organizations.permissions import (
    account_workspaces_for_user,
    customer_account_membership_for_user,
    user_can_manage_people,
    worker_profile_for_workspace,
)
from organizations.images import normalize_profile_photo
from .services import workforce_ledger
from .activity_services import activity_ledger


@login_required
def employee_photo_view(request, worker_id):
    worker = get_object_or_404(WorkerProfile.objects.select_related('user'), id=worker_id)
    active_workspace = getattr(request, 'active_organization', None)
    active_account = getattr(active_workspace, 'customer_account', None)
    can_view = (
        request.user.is_superuser
        or request.user.id == worker.user_id
        or (
            active_account
            and customer_account_membership_for_user(request.user, active_account)
            and worker.user.customer_accounts.filter(account=active_account, is_active=True).exists()
        )
    )
    if not can_view or not worker.photo:
        raise Http404
    try:
        content_type = mimetypes.guess_type(worker.photo.name)[0] or 'application/octet-stream'
        return FileResponse(worker.photo.open('rb'), content_type=content_type)
    except (FileNotFoundError, OSError, ValueError):
        raise Http404


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
        if request.POST.get('action') == 'update_operating_mode':
            operating_mode = request.POST.get('operating_mode')
            if operating_mode not in dict(customer_account.OPERATING_MODE_CHOICES):
                messages.error(request, 'Choose Solo Mode or Team Mode.')
                return redirect('workforce')
            with transaction.atomic():
                customer_account.operating_mode = operating_mode
                customer_account.save(update_fields=['operating_mode'])
                if operating_mode == 'solo':
                    owner_member, _ = CustomerAccountMember.objects.update_or_create(
                        account=customer_account,
                        user=customer_account.owner,
                        defaults={
                            'role': 'owner',
                            'can_work_jobs': True,
                            'is_active': True,
                        },
                    )
                    owner_worker, _ = WorkerProfile.objects.get_or_create(user=customer_account.owner)
                    for workspace in customer_account.workspaces.all():
                        WorkspaceMember.objects.update_or_create(
                            workspace=workspace,
                            user=customer_account.owner,
                            defaults={'role': 'admin', 'is_active': True},
                        )
                    owner_worker.workspaces.add(*customer_account.workspaces.all())
            label = 'Solo Mode' if operating_mode == 'solo' else 'Team Mode'
            messages.success(request, f'{label} is now active for this account.')
            return redirect('workforce')
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
        skills = Skill.objects.filter(
            Q(customer_account=customer_account) | Q(workspace__in=account_workspaces)
        ).distinct()
        zones = ServiceZone.objects.filter(workspace__in=account_workspaces)
    else:
        account_members = CustomerAccountMember.objects.none()
        workers = WorkerProfile.objects.none()
        active_assignments = JobAssignment.objects.none()
        skills = Skill.objects.none()
        zones = ServiceZone.objects.none()

    account_members = list(account_members)
    profiles_by_user = {
        profile.user_id: profile
        for profile in WorkerProfile.objects.filter(user_id__in=[member.user_id for member in account_members])
    }
    for member in account_members:
        member.worker_profile = profiles_by_user.get(member.user_id)
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


@login_required
def work_activity_ledger_view(request):
    active_org = getattr(request, 'active_organization', None)
    if not user_can_manage_people(request.user, active_org):
        raise PermissionDenied('Manager access is required to view work activity.')

    workspaces = account_workspaces_for_user(request.user, active_org).order_by('name')
    activities = WorkActivity.objects.filter(workspace__in=workspaces).select_related(
        'workspace', 'worker__user', 'job', 'assignment', 'material_run',
    )
    selected_workspace = request.GET.get('workspace', '')
    selected_worker = request.GET.get('worker', '')
    selected_type = request.GET.get('activity_type', '')
    start_date = parse_date(request.GET.get('start_date', ''))
    end_date = parse_date(request.GET.get('end_date', ''))
    allowed_workspace_ids = {str(item.id) for item in workspaces}
    if selected_workspace in allowed_workspace_ids:
        activities = activities.filter(workspace_id=selected_workspace)
    else:
        selected_workspace = ''
    if selected_worker.isdigit():
        activities = activities.filter(worker_id=int(selected_worker))
    else:
        selected_worker = ''
    if selected_type in dict(WorkActivity.ACTIVITY_TYPE_CHOICES):
        activities = activities.filter(activity_type=selected_type)
    else:
        selected_type = ''
    if start_date:
        activities = activities.filter(started_at__date__gte=start_date)
    if end_date:
        activities = activities.filter(started_at__date__lte=end_date)

    customer_account = getattr(active_org, 'customer_account', None)
    workers = WorkerProfile.objects.filter(
        user__customer_accounts__account=customer_account,
        user__customer_accounts__is_active=True,
        user__customer_accounts__can_work_jobs=True,
        workspaces__in=workspaces,
    ).select_related('user').distinct().order_by(
        'user__first_name', 'user__last_name', 'user__username',
    )
    ledger = activity_ledger(list(activities.order_by('-started_at', '-id')[:500]))
    return render(request, 'work_activity_ledger.html', {
        'ledger': ledger,
        'workspaces': workspaces,
        'workers': workers,
        'activity_types': WorkActivity.ACTIVITY_TYPE_CHOICES,
        'selected_workspace': selected_workspace,
        'selected_worker': selected_worker,
        'selected_type': selected_type,
        'start_date': start_date,
        'end_date': end_date,
    })


@login_required
def team_member_detail_view(request, member_id):
    active_org = getattr(request, 'active_organization', None)
    if not user_can_manage_people(request.user, active_org):
        raise PermissionDenied('Manager access is required to view employee records.')
    customer_account = getattr(active_org, 'customer_account', None)
    member = get_object_or_404(
        CustomerAccountMember.objects.select_related('user', 'account'),
        id=member_id,
        account=customer_account,
        is_active=True,
    )
    account_membership = customer_account_membership_for_user(request.user, customer_account)
    can_manage_account_team = request.user.is_superuser or bool(
        account_membership and account_membership.role in ('owner', 'admin')
    )
    worker, _ = WorkerProfile.objects.get_or_create(user=member.user)
    account_workspaces = customer_account.workspaces.order_by('name')
    worker.workspaces.add(*account_workspaces.filter(members__user=member.user, members__is_active=True).distinct())
    skills = Skill.objects.filter(
        Q(customer_account=customer_account) | Q(workspace__customer_account=customer_account)
    ).distinct().order_by('name')
    requirements = EmployeeDocumentRequirement.objects.filter(account=customer_account, is_active=True)

    if request.method == 'POST':
        action = request.POST.get('action')
        if action == 'update_profile':
            username = request.POST.get('username', '').strip()
            email = request.POST.get('email', '').strip().lower()
            if not username:
                messages.error(request, 'Enter a username for this employee.')
            elif member.user.__class__.objects.filter(username__iexact=username).exclude(id=member.user_id).exists():
                messages.error(request, 'That username is already in use.')
            elif not email or '@' not in email:
                messages.error(request, 'Enter a valid employee email address.')
            elif member.user.__class__.objects.filter(email__iexact=email).exclude(id=member.user_id).exists():
                messages.error(request, 'That email address is already in use.')
            else:
                member.user.first_name = request.POST.get('first_name', '').strip()
                member.user.last_name = request.POST.get('last_name', '').strip()
                member.user.username = username
                member.user.email = email
                member.user.save(update_fields=['first_name', 'last_name', 'username', 'email'])
                worker.phone = request.POST.get('phone', '').strip()
                worker.job_title = request.POST.get('job_title', '').strip()
                worker.start_date = parse_date(request.POST.get('start_date', ''))
                worker.home_street = request.POST.get('home_street', '').strip()
                worker.home_city = request.POST.get('home_city', '').strip()
                worker.home_state = request.POST.get('home_state', '').strip()
                worker.home_postal_code = request.POST.get('home_postal_code', '').strip()
                worker.home_country = request.POST.get('home_country', '').strip() or 'United States'
                worker.emergency_contact_name = request.POST.get('emergency_contact_name', '').strip()
                worker.emergency_contact_phone = request.POST.get('emergency_contact_phone', '').strip()
                employment_type = request.POST.get('employment_type', '')
                worker.employment_type = employment_type if employment_type in dict(WorkerProfile.EMPLOYMENT_TYPE_CHOICES) else ''
                photo = request.FILES.get('photo')
                if photo:
                    normalized_photo, photo_error = normalize_profile_photo(photo)
                    if photo_error:
                        messages.error(request, photo_error)
                        return redirect('team_member_detail', member_id=member.id)
                    worker.photo = normalized_photo
                worker.save()
                member.photo_required = request.POST.get('photo_required') == 'yes'
                member.drivers_license_required = request.POST.get('drivers_license_required') == 'yes'
                member.save(update_fields=['photo_required', 'drivers_license_required'])
                messages.success(request, 'Employee profile updated.')

        elif action == 'remove_employee':
            if not can_manage_account_team:
                raise PermissionDenied('Only the account owner or an account administrator can remove employees.')
            if member.role == 'owner' or member.user_id == customer_account.owner_id:
                messages.error(request, 'The customer account owner cannot be removed.')
            else:
                active_assignments = JobAssignment.objects.filter(
                    worker=worker,
                    job__organization__customer_account=customer_account,
                ).exclude(job__status__in=['completed', 'canceled'])
                if active_assignments.exists():
                    messages.error(
                        request,
                        f'Unassign this employee from {active_assignments.count()} active job(s) before removing access.',
                    )
                else:
                    with transaction.atomic():
                        member.is_active = False
                        member.can_work_jobs = False
                        member.can_view_billing = False
                        member.save(update_fields=['is_active', 'can_work_jobs', 'can_view_billing'])
                        WorkspaceMember.objects.filter(
                            workspace__customer_account=customer_account,
                            user=member.user,
                        ).update(is_active=False)
                        worker.workspaces.remove(*customer_account.workspaces.all())
                        if not CustomerAccountMember.objects.filter(user=member.user, is_active=True).exists():
                            member.user.is_active = False
                            member.user.save(update_fields=['is_active'])
                    messages.success(request, 'Employee access removed. Historical work records were preserved.')
                    return redirect('workforce')

        elif action == 'update_skills':
            selected_ids = {int(value) for value in request.POST.getlist('skill_ids') if value.isdigit()}
            allowed = {item.id: item for item in skills}
            worker.skills.filter(skill_id__in=set(allowed) - selected_ids).delete()
            for skill_id in selected_ids & set(allowed):
                level = request.POST.get(f'skill_level_{skill_id}', '2')
                level = int(level) if level in {'1', '2', '3'} else 2
                WorkerSkill.objects.update_or_create(
                    worker=worker,
                    skill=allowed[skill_id],
                    defaults={'proficiency_level': level},
                )
            messages.success(request, 'Employee skills updated across the account.')

        elif action == 'create_document_requirement':
            title = request.POST.get('title', '').strip()
            document_type = request.POST.get('document_type', 'other')
            if title and document_type in dict(EmployeeDocumentRequirement.DOCUMENT_TYPE_CHOICES):
                requirement = EmployeeDocumentRequirement.objects.create(
                    account=customer_account,
                    title=title,
                    document_type=document_type,
                    instructions=request.POST.get('instructions', '').strip(),
                )
                requirement.requested_members.add(member)
                messages.success(request, f'Document request “{title}” added.')
            else:
                messages.error(request, 'Enter a document request title and type.')

        elif action == 'update_document_requests':
            selected_ids = {int(value) for value in request.POST.getlist('requirement_ids') if value.isdigit()}
            for requirement in requirements:
                if requirement.id in selected_ids:
                    requirement.requested_members.add(member)
                else:
                    requirement.requested_members.remove(member)
            messages.success(request, 'Document requests updated.')

        elif action == 'review_document':
            document = get_object_or_404(EmployeeDocument, id=request.POST.get('document_id'), account=customer_account, user=member.user)
            new_status = request.POST.get('status')
            if new_status in dict(EmployeeDocument.STATUS_CHOICES):
                document.status = new_status
                document.review_notes = request.POST.get('review_notes', '').strip()
                document.reviewed_by = request.user
                document.reviewed_at = timezone.now()
                document.save(update_fields=['status', 'review_notes', 'reviewed_by', 'reviewed_at'])
                messages.success(request, 'Document review saved.')
        return redirect('team_member_detail', member_id=member.id)

    assignments = JobAssignment.objects.filter(
        worker=worker,
        job__organization__customer_account=customer_account,
    ).select_related('job', 'job__organization', 'job__account', 'job__property').order_by('-job__scheduled_start', '-id')[:250]
    ledger = workforce_ledger(assignments)
    assigned_skill_ids = {
        item.skill_id: item.proficiency_level
        for item in worker.skills.filter(skill__in=skills)
    }
    requested_requirement_ids = set(member.document_requests.values_list('id', flat=True))
    for skill in skills:
        skill.assigned_level = assigned_skill_ids.get(skill.id)
    for requirement in requirements:
        requirement.is_requested = requirement.id in requested_requirement_ids
    documents = EmployeeDocument.objects.filter(account=customer_account, user=member.user).select_related('requirement', 'reviewed_by')
    return render(request, 'team_member_detail.html', {
        'member': member,
        'worker': worker,
        'account_workspaces': account_workspaces,
        'skills': skills,
        'proficiency_choices': WorkerSkill.PROFICIENCY_CHOICES,
        'requirements': requirements,
        'documents': documents,
        'document_types': EmployeeDocumentRequirement.DOCUMENT_TYPE_CHOICES,
        'employment_type_choices': WorkerProfile.EMPLOYMENT_TYPE_CHOICES,
        'document_status_choices': EmployeeDocument.STATUS_CHOICES,
        'ledger': ledger,
        'can_manage_account_team': can_manage_account_team,
    })


@login_required
def employee_document_download_view(request, document_id):
    document = get_object_or_404(EmployeeDocument.objects.select_related('account', 'user'), id=document_id)
    active_org = getattr(request, 'active_organization', None)
    same_account = active_org and active_org.customer_account_id == document.account_id
    if request.user.id != document.user_id and not (same_account and user_can_manage_people(request.user, active_org)):
        raise PermissionDenied('You cannot access this employee document.')
    try:
        return FileResponse(document.file.open('rb'), as_attachment=True, filename=document.file.name.rsplit('/', 1)[-1])
    except FileNotFoundError as exc:
        raise Http404('Document file is unavailable.') from exc

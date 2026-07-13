import json

from django.contrib import messages
from django.contrib.auth import get_user_model, login
from django.contrib.auth.decorators import login_required
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.shortcuts import redirect, render
from django.utils.text import slugify
from fsm.models import JobAssignment

from .models import (
    CustomField,
    FormLayout,
    ServiceZone,
    Skill,
    WorkerProfile,
    WorkerSkill,
    WorkspaceEmailConnection,
    WorkspaceEmailDomain,
    WorkspaceMember,
    Workspace,
)
from .permissions import user_can_manage_workspace, worker_profile_for_workspace


TARGET_MODEL_CHOICES = [
    ('account', 'Account'),
    ('contact', 'Contact'),
    ('property', 'Property'),
    ('job', 'Job'),
    ('worker', 'Worker'),
]

STANDARD_MODULE_FIELDS = {
    'account': [
        {'key': 'name', 'label': 'Account Name', 'field_type': 'text'},
        {'key': 'phone', 'label': 'Phone', 'field_type': 'text'},
        {'key': 'email', 'label': 'Email', 'field_type': 'text'},
        {'key': 'website', 'label': 'Website', 'field_type': 'text'},
        {'key': 'billing_street', 'label': 'Billing Street', 'field_type': 'text'},
        {'key': 'billing_city', 'label': 'Billing City', 'field_type': 'text'},
        {'key': 'billing_state', 'label': 'Billing State', 'field_type': 'text'},
        {'key': 'billing_postal_code', 'label': 'Billing ZIP', 'field_type': 'text'},
        {'key': 'billing_country', 'label': 'Billing Country', 'field_type': 'text'},
    ],
    'contact': [
        {'key': 'first_name', 'label': 'First Name', 'field_type': 'text'},
        {'key': 'last_name', 'label': 'Last Name', 'field_type': 'text'},
        {'key': 'email', 'label': 'Email', 'field_type': 'text'},
        {'key': 'phone', 'label': 'Phone', 'field_type': 'text'},
        {'key': 'mobile', 'label': 'Mobile', 'field_type': 'text'},
        {'key': 'mailing_street', 'label': 'Mailing Street', 'field_type': 'text'},
        {'key': 'mailing_city', 'label': 'Mailing City', 'field_type': 'text'},
        {'key': 'mailing_state', 'label': 'Mailing State', 'field_type': 'text'},
        {'key': 'mailing_postal_code', 'label': 'Mailing ZIP', 'field_type': 'text'},
        {'key': 'lead_source', 'label': 'Lead Source', 'field_type': 'text'},
        {'key': 'status', 'label': 'Status', 'field_type': 'text'},
        {'key': 'is_primary', 'label': 'Primary Contact', 'field_type': 'boolean'},
    ],
    'property': [
        {'key': 'name', 'label': 'Property Name', 'field_type': 'text'},
        {'key': 'address', 'label': 'Address', 'field_type': 'textarea'},
        {'key': 'unit_number', 'label': 'Unit / Suite', 'field_type': 'text'},
        {'key': 'gate_code', 'label': 'Gate Code', 'field_type': 'text'},
    ],
    'job': [
        {'key': 'title', 'label': 'Job Title', 'field_type': 'text'},
        {'key': 'status', 'label': 'Status', 'field_type': 'dropdown'},
        {'key': 'job_type', 'label': 'Job Type', 'field_type': 'dropdown'},
        {'key': 'scheduled_start', 'label': 'Scheduled Start', 'field_type': 'date'},
    ],
    'worker': [
        {'key': 'user', 'label': 'User', 'field_type': 'text'},
        {'key': 'phone', 'label': 'Phone', 'field_type': 'text'},
        {'key': 'is_admin', 'label': 'Workspace Admin', 'field_type': 'boolean'},
    ],
}


def split_csv(value):
    return [item.strip() for item in value.split(',') if item.strip()]


def optional_int(value):
    try:
        return int(value) if value not in ['', None] else None
    except (TypeError, ValueError):
        return None


def unique_workspace_slug(name):
    base = slugify(name)[:45] or 'workspace'
    candidate = base
    counter = 2
    while Workspace.objects.filter(slug=candidate).exists():
        candidate = f'{base[:40]}-{counter}'
        counter += 1
    return candidate


@transaction.atomic
def signup_view(request):
    if request.user.is_authenticated:
        return redirect('workspace_create')
    if request.method == 'POST':
        company_name = request.POST.get('company_name', '').strip()
        first_name = request.POST.get('first_name', '').strip()
        last_name = request.POST.get('last_name', '').strip()
        email = request.POST.get('email', '').strip().lower()
        password = request.POST.get('password', '')
        User = get_user_model()
        errors = []
        if not company_name:
            errors.append('Company name is required.')
        if not email or '@' not in email:
            errors.append('Enter a valid work email.')
        if User.objects.filter(email__iexact=email).exists():
            errors.append('An account already exists for that email. Sign in instead.')
        try:
            validate_password(password)
        except ValidationError as exc:
            errors.extend(exc.messages)
        if errors:
            for error in errors:
                messages.error(request, error)
        else:
            user = User.objects.create_user(
                username=email,
                email=email,
                password=password,
                first_name=first_name,
                last_name=last_name,
            )
            workspace = Workspace.objects.create(
                name=company_name,
                slug=unique_workspace_slug(company_name),
                created_by=user,
            )
            WorkspaceMember.objects.create(workspace=workspace, user=user, role='admin', is_active=True)
            from finance.models import SubscriptionPlan, WorkspaceSubscription

            plan = SubscriptionPlan.objects.filter(is_active=True).first()
            if plan:
                WorkspaceSubscription.objects.create(
                    workspace=workspace,
                    plan=plan,
                    billing_email=email,
                    seat_count=1,
                    status='trialing',
                )
            login(request, user)
            request.session['active_org_id'] = str(workspace.id)
            return redirect('billing_overview')
    return render(request, 'registration/signup.html')


@login_required
@transaction.atomic
def create_workspace_view(request):
    if request.method == 'POST':
        name = request.POST.get('name', '').strip()
        billing_email = request.POST.get('billing_email', '').strip().lower()
        if not name:
            messages.error(request, 'Workspace name is required.')
        else:
            workspace = Workspace.objects.create(
                name=name,
                slug=unique_workspace_slug(name),
                created_by=request.user,
            )
            WorkspaceMember.objects.create(
                workspace=workspace,
                user=request.user,
                role='admin',
                is_active=True,
            )
            from finance.models import SubscriptionPlan, WorkspaceSubscription

            plan = SubscriptionPlan.objects.filter(is_active=True).first()
            if plan:
                WorkspaceSubscription.objects.create(
                    workspace=workspace,
                    plan=plan,
                    billing_email=billing_email or request.user.email,
                    seat_count=1,
                    status='trialing',
                )
            request.session['active_org_id'] = str(workspace.id)
            messages.success(request, f'Workspace "{workspace.name}" created. Complete billing when ready.')
            return redirect('admin_console')
    return render(request, 'workspace_create.html')


@login_required
def admin_console_view(request):
    active_org = getattr(request, 'active_organization', None)

    if not active_org:
        messages.error(request, 'Select an organization before opening Company Setup.')
        return redirect('dashboard')

    if not user_can_manage_workspace(request.user, active_org):
        raise PermissionDenied('You do not have permission to manage this organization.')

    if request.method == 'POST':
        action = request.POST.get('action')

        if action == 'create_custom_field':
            label = request.POST.get('label', '').strip()
            target_model = request.POST.get('target_model', '').strip()
            field_type = request.POST.get('field_type', '').strip()
            internal_name = request.POST.get('internal_name', '').strip()
            options = split_csv(request.POST.get('options', ''))

            if not internal_name and label:
                internal_name = slugify(label).replace('-', '_')[:100]

            if not label or not target_model or not field_type or not internal_name:
                messages.error(request, 'Custom fields need a target, label, type, and internal name.')
            else:
                CustomField.objects.create(
                    workspace=active_org,
                    target_model=target_model,
                    label=label,
                    internal_name=internal_name,
                    field_type=field_type,
                    options=options,
                    is_required=request.POST.get('is_required') == 'on',
                )
                messages.success(request, f'Custom field "{label}" added.')

        elif action == 'delete_custom_field':
            CustomField.objects.filter(workspace=active_org, id=request.POST.get('id')).delete()
            messages.success(request, 'Custom field removed.')

        elif action == 'save_form_layout':
            target_model = request.POST.get('target_model', '').strip()
            raw_layout = request.POST.get('layout_json', '[]')

            if target_model not in dict(TARGET_MODEL_CHOICES):
                messages.error(request, 'Choose a valid module before saving the layout.')
            else:
                try:
                    layout_json = json.loads(raw_layout)
                    if not isinstance(layout_json, list):
                        raise ValueError
                except (TypeError, ValueError, json.JSONDecodeError):
                    messages.error(request, 'The module layout could not be saved because the layout data is invalid.')
                else:
                    layout = FormLayout.objects.filter(workspace=active_org, target_model=target_model).first()
                    if layout:
                        layout.layout_json = layout_json
                        layout.save(update_fields=['layout_json'])
                    else:
                        FormLayout.objects.create(
                            workspace=active_org,
                            target_model=target_model,
                            layout_json=layout_json,
                        )
                    messages.success(request, 'Module layout saved.')

        elif action == 'create_email_domain':
            domain = request.POST.get('domain', '').strip().lower()
            domain = domain.replace('https://', '').replace('http://', '').strip('/')
            if not domain or '.' not in domain:
                messages.error(request, 'Enter a valid workspace email domain.')
            else:
                WorkspaceEmailDomain.objects.get_or_create(
                    workspace=active_org,
                    domain=domain,
                    defaults={
                        'verification_notes': request.POST.get('verification_notes', '').strip(),
                    },
                )
                messages.success(request, f'Email domain "{domain}" added to this workspace.')

        elif action == 'delete_email_domain':
            WorkspaceEmailDomain.objects.filter(workspace=active_org, id=request.POST.get('id')).delete()
            messages.success(request, 'Email domain removed.')

        elif action == 'create_email_connection':
            from_email = request.POST.get('from_email', '').strip().lower()
            display_name = request.POST.get('display_name', '').strip()
            connection_type = request.POST.get('connection_type', '').strip()
            domain = WorkspaceEmailDomain.objects.filter(
                workspace=active_org,
                id=request.POST.get('domain_id'),
            ).first()

            if not from_email or '@' not in from_email or not display_name:
                messages.error(request, 'Email connections need a display name and sender email.')
            elif connection_type not in dict(WorkspaceEmailConnection.CONNECTION_TYPES):
                messages.error(request, 'Choose a valid email connection type.')
            else:
                WorkspaceEmailConnection.objects.create(
                    workspace=active_org,
                    domain=domain,
                    display_name=display_name,
                    from_email=from_email,
                    connection_type=connection_type,
                    status='needs_auth',
                    incoming_host=request.POST.get('incoming_host', '').strip(),
                    incoming_port=optional_int(request.POST.get('incoming_port')),
                    outgoing_host=request.POST.get('outgoing_host', '').strip(),
                    outgoing_port=optional_int(request.POST.get('outgoing_port')),
                    use_ssl=request.POST.get('use_ssl') == 'on',
                    username=request.POST.get('username', '').strip(),
                    secret_reference=request.POST.get('secret_reference', '').strip(),
                    created_by=request.user,
                )
                messages.success(request, f'Workspace mailbox "{from_email}" added.')

        elif action == 'delete_email_connection':
            WorkspaceEmailConnection.objects.filter(workspace=active_org, id=request.POST.get('id')).delete()
            messages.success(request, 'Email connection removed.')

        elif action == 'create_skill':
            name = request.POST.get('name', '').strip()
            if not name:
                messages.error(request, 'Skill name is required.')
            else:
                Skill.objects.create(
                    workspace=active_org,
                    name=name,
                    description=request.POST.get('description', '').strip(),
                )
                messages.success(request, f'Skill "{name}" added.')

        elif action == 'delete_skill':
            Skill.objects.filter(workspace=active_org, id=request.POST.get('id')).delete()
            messages.success(request, 'Skill removed.')

        elif action == 'create_service_zone':
            name = request.POST.get('name', '').strip()
            zip_codes = split_csv(request.POST.get('active_zip_codes', ''))
            if not name:
                messages.error(request, 'Service zone name is required.')
            else:
                ServiceZone.objects.create(
                    workspace=active_org,
                    name=name,
                    active_zip_codes=zip_codes,
                )
                messages.success(request, f'Service zone "{name}" added.')

        elif action == 'delete_service_zone':
            ServiceZone.objects.filter(workspace=active_org, id=request.POST.get('id')).delete()
            messages.success(request, 'Service zone removed.')

        elif action == 'assign_worker_skill':
            worker = WorkerProfile.objects.filter(
                workspaces=active_org,
                id=request.POST.get('worker_id'),
            ).first()
            skill = Skill.objects.filter(
                workspace=active_org,
                id=request.POST.get('skill_id'),
            ).first()

            if not worker or not skill:
                messages.error(request, 'Choose a valid worker and skill.')
            else:
                WorkerSkill.objects.update_or_create(
                    worker=worker,
                    skill=skill,
                    defaults={'proficiency_level': request.POST.get('proficiency_level', 3)},
                )
                messages.success(request, 'Worker skill updated.')

        elif action == 'delete_worker_skill':
            WorkerSkill.objects.filter(
                worker__workspaces=active_org,
                skill__workspace=active_org,
                id=request.POST.get('id'),
            ).delete()
            messages.success(request, 'Worker skill removed.')

        elif action == 'invite_member':
            email = request.POST.get('email', '').strip().lower()
            first_name = request.POST.get('first_name', '').strip()
            last_name = request.POST.get('last_name', '').strip()
            role = request.POST.get('role', 'worker')
            if role not in dict(WorkspaceMember.ROLE_CHOICES):
                role = 'worker'
            existing_member = WorkspaceMember.objects.filter(workspace=active_org, user__email__iexact=email).exists()
            if not email or '@' not in email:
                messages.error(request, 'Enter a valid user email address.')
            elif existing_member:
                messages.error(request, 'That user already belongs to this workspace.')
            elif request.POST.get('confirm_price') != 'yes':
                messages.error(request, 'Confirm the displayed monthly estimate before adding the user.')
            else:
                User = get_user_model()
                user = User.objects.filter(email__iexact=email).first()
                created_user = False
                if not user:
                    username = email
                    user = User(username=username, email=email, first_name=first_name, last_name=last_name)
                    user.set_unusable_password()
                    user.save()
                    created_user = True
                WorkspaceMember.objects.create(workspace=active_org, user=user, role=role, is_active=True)
                worker, _ = WorkerProfile.objects.get_or_create(user=user)
                worker.workspaces.add(active_org)
                worker.is_admin = role in {'admin', 'manager'}
                worker.save(update_fields=['is_admin'])

                from finance.billing_views import sync_subscription_seats
                from finance.models import BillingEvent, WorkspaceSubscription

                subscription = WorkspaceSubscription.objects.filter(workspace=active_org).select_related('plan').first()
                seat_count = WorkspaceMember.objects.filter(workspace=active_org, is_active=True).count()
                if subscription:
                    stripe_synced = sync_subscription_seats(subscription, seat_count)
                    BillingEvent.objects.create(
                        workspace=active_org,
                        event_type='seats.updated',
                        summary=f'User added; subscription now has {seat_count} seats.',
                        actor=request.user,
                        metadata={'stripe_synced': stripe_synced, 'member_email': email},
                    )
                message = f'{email} added to the workspace.'
                if created_user:
                    message += ' Send the user a password-reset link so they can activate the account.'
                messages.success(request, message)

        return redirect('admin_console')

    custom_fields = CustomField.objects.filter(workspace=active_org).order_by('target_model', 'label')
    form_layouts = FormLayout.objects.filter(workspace=active_org).order_by('target_model')
    email_domains = WorkspaceEmailDomain.objects.filter(workspace=active_org).order_by('domain')
    email_connections = WorkspaceEmailConnection.objects.filter(
        workspace=active_org,
    ).select_related('domain', 'created_by').order_by('from_email')
    skills = Skill.objects.filter(workspace=active_org).order_by('name')
    service_zones = ServiceZone.objects.filter(workspace=active_org).order_by('name')
    workers = WorkerProfile.objects.filter(workspaces=active_org).select_related('user').order_by(
        'user__first_name',
        'user__last_name',
        'user__username',
    )
    worker_skills = WorkerSkill.objects.filter(
        worker__workspaces=active_org,
        skill__workspace=active_org,
    ).select_related('worker__user', 'skill').order_by('worker__user__username', 'skill__name')
    members = WorkspaceMember.objects.filter(workspace=active_org).select_related('user').order_by('user__username')

    from finance.models import SubscriptionPlan, WorkspaceSubscription
    from finance.pricing import monthly_price

    subscription = WorkspaceSubscription.objects.filter(workspace=active_org).select_related('plan').first()
    if not subscription:
        plan = SubscriptionPlan.objects.filter(is_active=True).first()
        if plan:
            subscription = WorkspaceSubscription.objects.create(
                workspace=active_org,
                plan=plan,
                billing_email=request.user.email,
                seat_count=max(members.filter(is_active=True).count(), 1),
            )
    active_seats = max(members.filter(is_active=True).count(), 1)

    context = {
        'custom_fields': custom_fields,
        'custom_fields_json': [
            {
                'id': field.id,
                'target_model': field.target_model,
                'label': field.label,
                'internal_name': field.internal_name,
                'field_type': field.field_type,
                'is_required': field.is_required,
            }
            for field in custom_fields
        ],
        'field_types': CustomField.FIELD_TYPES,
        'target_model_choices': TARGET_MODEL_CHOICES,
        'standard_module_fields': STANDARD_MODULE_FIELDS,
        'form_layouts': form_layouts,
        'form_layouts_json': [
            {
                'target_model': layout.target_model,
                'layout_json': layout.layout_json,
            }
            for layout in form_layouts
        ],
        'email_domains': email_domains,
        'email_connections': email_connections,
        'email_connection_types': WorkspaceEmailConnection.CONNECTION_TYPES,
        'skills': skills,
        'service_zones': service_zones,
        'workers': workers,
        'worker_skills': worker_skills,
        'members': members,
        'proficiency_choices': WorkerSkill.PROFICIENCY_CHOICES,
        'member_role_choices': WorkspaceMember.ROLE_CHOICES,
        'subscription': subscription,
        'active_seats': active_seats,
        'current_monthly_price': monthly_price(subscription.plan, active_seats) if subscription else 0,
        'next_monthly_price': monthly_price(subscription.plan, active_seats + 1) if subscription else 0,
        'stats': {
            'custom_fields': custom_fields.count(),
            'email_domains': email_domains.count(),
            'email_connections': email_connections.count(),
            'skills': skills.count(),
            'service_zones': service_zones.count(),
            'workers': workers.count(),
        },
    }
    return render(request, 'admin_console.html', context)


@login_required
def employee_profile_view(request):
    active_org = getattr(request, 'active_organization', None)
    worker_profile = worker_profile_for_workspace(request.user, active_org)

    assignments = JobAssignment.objects.none()
    if active_org and worker_profile:
        assignments = (
            JobAssignment.objects.filter(
                worker=worker_profile,
                job__organization=active_org,
            )
            .select_related('job', 'job__account', 'job__property')
            .order_by('-job__scheduled_start', '-job__id')
        )

    open_assignments = assignments.exclude(job__status__in=['completed', 'canceled'])
    completed_assignments = assignments.filter(job__status='completed')[:8]

    context = {
        'worker_profile': worker_profile,
        'open_assignments': open_assignments,
        'completed_assignments': completed_assignments,
        'stats': {
            'open_jobs': open_assignments.count(),
            'completed_jobs': assignments.filter(job__status='completed').count(),
            'clocked_in': open_assignments.filter(clocked_in_at__isnull=False, clocked_out_at__isnull=True).count(),
        },
    }
    return render(request, 'employee_profile.html', context)

# Create your views here.

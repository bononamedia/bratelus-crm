from django.db import migrations


COLORS = ['#2563eb', '#059669', '#d97706', '#7c3aed', '#dc2626', '#0891b2', '#db2777', '#4f46e5']
ROLE_PRIORITY = {'employee': 1, 'manager': 2, 'admin': 3, 'owner': 4}


def normalized_role(workspace_role, is_owner=False):
    if is_owner:
        return 'owner'
    return {'admin': 'admin', 'manager': 'manager'}.get(workspace_role, 'employee')


def upsert_account_member(CustomerAccountMember, account, user_id, role, can_work=False, can_view_billing=False):
    member = CustomerAccountMember.objects.filter(account_id=account.id, user_id=user_id).first()
    if not member:
        CustomerAccountMember.objects.create(
            account_id=account.id,
            user_id=user_id,
            role=role,
            can_work_jobs=can_work,
            can_view_billing=can_view_billing or role in {'owner', 'admin'},
            is_active=True,
        )
        return
    changed = []
    if ROLE_PRIORITY[role] > ROLE_PRIORITY[member.role]:
        member.role = role
        changed.append('role')
    if can_work and not member.can_work_jobs:
        member.can_work_jobs = True
        changed.append('can_work_jobs')
    if (can_view_billing or role in {'owner', 'admin'}) and not member.can_view_billing:
        member.can_view_billing = True
        changed.append('can_view_billing')
    if not member.is_active:
        member.is_active = True
        changed.append('is_active')
    if changed:
        member.save(update_fields=changed)


def backfill_legacy_accounts(apps, schema_editor):
    CustomerAccount = apps.get_model('organizations', 'CustomerAccount')
    CustomerAccountMember = apps.get_model('organizations', 'CustomerAccountMember')
    Workspace = apps.get_model('organizations', 'Workspace')
    WorkspaceMember = apps.get_model('organizations', 'WorkspaceMember')
    WorkerProfile = apps.get_model('organizations', 'WorkerProfile')
    User = apps.get_model('auth', 'User')

    accounts_by_owner = {
        account.owner_id: account
        for account in CustomerAccount.objects.all()
        if not account.owner.is_superuser
    }
    platform_owner_id = User.objects.filter(is_superuser=True, is_active=True).values_list('id', flat=True).first()

    for index, workspace in enumerate(Workspace.objects.order_by('created_at', 'id')):
        if workspace.customer_account_id:
            account = workspace.customer_account
            owner_id = account.owner_id
        else:
            owner_id = workspace.created_by_id
            if not owner_id:
                owner_id = WorkspaceMember.objects.filter(workspace=workspace, role='admin', is_active=True).values_list('user_id', flat=True).first()
            if not owner_id:
                owner_id = WorkspaceMember.objects.filter(workspace=workspace, role='manager', is_active=True).values_list('user_id', flat=True).first()
            if not owner_id:
                owner_id = WorkspaceMember.objects.filter(workspace=workspace, is_active=True).values_list('user_id', flat=True).first()
            if not owner_id:
                owner_id = WorkerProfile.objects.filter(workspaces=workspace).values_list('user_id', flat=True).first()
            if not owner_id:
                owner_id = platform_owner_id
            if not owner_id:
                continue

            owner_is_superuser = User.objects.filter(id=owner_id, is_superuser=True).exists()
            account = None if owner_is_superuser else accounts_by_owner.get(owner_id)
            if not account:
                account = CustomerAccount.objects.create(name=workspace.name, owner_id=owner_id)
                if not owner_is_superuser:
                    accounts_by_owner[owner_id] = account
            workspace.customer_account_id = account.id
            workspace.calendar_color = COLORS[index % len(COLORS)]
            workspace.save(update_fields=['customer_account', 'calendar_color'])

        worker_user_ids = set(WorkerProfile.objects.filter(workspaces=workspace).values_list('user_id', flat=True))
        for member in WorkspaceMember.objects.filter(workspace=workspace, is_active=True):
            role = normalized_role(member.role, member.user_id == owner_id)
            upsert_account_member(
                CustomerAccountMember,
                account,
                member.user_id,
                role,
                can_work=member.user_id in worker_user_ids or member.role == 'field_worker',
                can_view_billing=member.can_view_billing,
            )
        for worker_user_id in worker_user_ids:
            upsert_account_member(
                CustomerAccountMember,
                account,
                worker_user_id,
                normalized_role('employee', worker_user_id == owner_id),
                can_work=True,
            )


class Migration(migrations.Migration):
    dependencies = [('organizations', '0006_customer_account_team')]

    operations = [
        migrations.RunPython(backfill_legacy_accounts, migrations.RunPython.noop),
    ]

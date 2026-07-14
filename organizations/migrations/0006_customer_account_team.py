from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion
import uuid


COLORS = ['#2563eb', '#059669', '#d97706', '#7c3aed', '#dc2626', '#0891b2', '#db2777', '#4f46e5']


def build_customer_accounts(apps, schema_editor):
    CustomerAccount = apps.get_model('organizations', 'CustomerAccount')
    CustomerAccountMember = apps.get_model('organizations', 'CustomerAccountMember')
    Workspace = apps.get_model('organizations', 'Workspace')
    WorkspaceMember = apps.get_model('organizations', 'WorkspaceMember')
    WorkerProfile = apps.get_model('organizations', 'WorkerProfile')
    User = apps.get_model('auth', 'User')

    accounts_by_owner = {}
    for index, workspace in enumerate(Workspace.objects.order_by('created_at', 'id')):
        owner_id = workspace.created_by_id
        if not owner_id:
            owner_id = WorkspaceMember.objects.filter(
                workspace_id=workspace.id,
                role='admin',
                is_active=True,
            ).values_list('user_id', flat=True).first()
        if not owner_id:
            continue
        owner_is_superuser = User.objects.filter(id=owner_id, is_superuser=True).exists()
        grouping_key = ('workspace', workspace.id) if owner_is_superuser else ('owner', owner_id)
        account = accounts_by_owner.get(grouping_key)
        if not account:
            account = CustomerAccount.objects.create(name=workspace.name, owner_id=owner_id)
            accounts_by_owner[grouping_key] = account
        workspace.customer_account_id = account.id
        workspace.calendar_color = COLORS[index % len(COLORS)]
        workspace.save(update_fields=['customer_account', 'calendar_color'])

        worker_user_ids = set(WorkerProfile.objects.filter(workspaces=workspace).values_list('user_id', flat=True))
        for member in WorkspaceMember.objects.filter(workspace=workspace, is_active=True):
            role = 'owner' if member.user_id == owner_id else member.role
            if role == 'field_worker':
                role = 'employee'
            CustomerAccountMember.objects.update_or_create(
                account_id=account.id,
                user_id=member.user_id,
                defaults={
                    'role': role,
                    'can_work_jobs': member.user_id in worker_user_ids or member.role == 'field_worker',
                    'can_view_billing': member.can_view_billing or role in {'owner', 'admin'},
                    'is_active': True,
                },
            )


class Migration(migrations.Migration):
    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('organizations', '0005_user_passkey_credential'),
    ]

    operations = [
        migrations.CreateModel(
            name='CustomerAccount',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('name', models.CharField(max_length=255)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('owner', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='owned_customer_accounts', to=settings.AUTH_USER_MODEL)),
            ],
            options={'db_table': 'workspaces_customeraccount'},
        ),
        migrations.CreateModel(
            name='CustomerAccountMember',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('role', models.CharField(choices=[('owner', 'Owner'), ('admin', 'Administrator'), ('manager', 'Manager'), ('employee', 'Employee')], default='employee', max_length=20)),
                ('can_work_jobs', models.BooleanField(default=False)),
                ('can_view_billing', models.BooleanField(default=False)),
                ('is_active', models.BooleanField(default=True)),
                ('account', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='members', to='organizations.customeraccount')),
                ('user', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='customer_accounts', to=settings.AUTH_USER_MODEL)),
            ],
            options={'db_table': 'workspaces_customeraccountmember', 'unique_together': {('account', 'user')}},
        ),
        migrations.AddField(
            model_name='workspace',
            name='calendar_color',
            field=models.CharField(default='#2563eb', max_length=7),
        ),
        migrations.AddField(
            model_name='workspace',
            name='customer_account',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name='workspaces', to='organizations.customeraccount'),
        ),
        migrations.RunPython(build_customer_accounts, migrations.RunPython.noop),
    ]

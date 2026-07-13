from django.db import migrations, models


def migrate_worker_role(apps, schema_editor):
    WorkspaceMember = apps.get_model('organizations', 'WorkspaceMember')
    WorkspaceMember.objects.filter(role='worker').update(role='field_worker')


class Migration(migrations.Migration):
    dependencies = [('organizations', '0003_workspace_created_by')]

    operations = [
        migrations.AddField(
            model_name='workspacemember',
            name='can_view_billing',
            field=models.BooleanField(default=False),
        ),
        migrations.AlterField(
            model_name='workspacemember',
            name='role',
            field=models.CharField(
                choices=[
                    ('admin', 'Admin'),
                    ('manager', 'Manager'),
                    ('employee', 'Employee'),
                    ('field_worker', 'Field Work'),
                ],
                default='field_worker',
                max_length=20,
            ),
        ),
        migrations.RunPython(migrate_worker_role, migrations.RunPython.noop),
        migrations.AddField(model_name='workerprofile', name='employment_type', field=models.CharField(blank=True, choices=[('1099', '1099 Contractor'), ('w2', 'W-2 Employee'), ('other', 'Other')], max_length=20)),
        migrations.AddField(model_name='workerprofile', name='home_street', field=models.CharField(blank=True, max_length=255)),
        migrations.AddField(model_name='workerprofile', name='home_city', field=models.CharField(blank=True, max_length=100)),
        migrations.AddField(model_name='workerprofile', name='home_state', field=models.CharField(blank=True, max_length=100)),
        migrations.AddField(model_name='workerprofile', name='home_postal_code', field=models.CharField(blank=True, max_length=20)),
        migrations.AddField(model_name='workerprofile', name='home_country', field=models.CharField(blank=True, default='United States', max_length=100)),
        migrations.AddField(model_name='workerprofile', name='emergency_contact_name', field=models.CharField(blank=True, max_length=150)),
        migrations.AddField(model_name='workerprofile', name='emergency_contact_phone', field=models.CharField(blank=True, max_length=30)),
        migrations.AddField(model_name='workerprofile', name='current_balance', field=models.DecimalField(decimal_places=2, default=0, max_digits=10)),
        migrations.AddField(model_name='workerprofile', name='next_payment_date', field=models.DateField(blank=True, null=True)),
    ]

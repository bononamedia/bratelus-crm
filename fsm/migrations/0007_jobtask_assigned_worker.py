import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('fsm', '0006_work_activity_ledger'),
        ('organizations', '0008_employee_profiles_documents_global_skills'),
    ]

    operations = [
        migrations.AddField(
            model_name='jobtask',
            name='assigned_worker',
            field=models.ForeignKey(
                blank=True,
                help_text='Optional task owner. Leave blank for any assigned crew member.',
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='assigned_job_tasks',
                to='organizations.workerprofile',
            ),
        ),
    ]

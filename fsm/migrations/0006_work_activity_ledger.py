import django.db.models.deletion
import django.utils.timezone
from django.db import migrations, models


def backfill_assignment_activities(apps, schema_editor):
    JobAssignment = apps.get_model('fsm', 'JobAssignment')
    WorkActivity = apps.get_model('fsm', 'WorkActivity')
    open_by_worker = {}
    assignments = JobAssignment.objects.filter(clocked_in_at__isnull=False).select_related('job').order_by(
        'worker_id', 'clocked_in_at', 'id'
    )
    for assignment in assignments:
        ended_at = assignment.clocked_out_at or assignment.work_completed_at
        previous_open = open_by_worker.get(assignment.worker_id)
        if previous_open:
            previous_open.ended_at = assignment.clocked_in_at
            previous_open.save(update_fields=['ended_at'])
        activity = WorkActivity.objects.create(
            workspace_id=assignment.job.organization_id,
            worker_id=assignment.worker_id,
            job_id=assignment.job_id,
            assignment_id=assignment.id,
            activity_type='onsite_work',
            is_paid=True,
            started_at=assignment.clocked_in_at,
            ended_at=ended_at,
            start_lat=0,
            start_lng=0,
            note='Backfilled from the original job clock.',
        )
        open_by_worker[assignment.worker_id] = activity if ended_at is None else None


class Migration(migrations.Migration):
    dependencies = [
        ('fsm', '0005_job_problem_reporting'),
    ]

    operations = [
        migrations.CreateModel(
            name='MaterialRun',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('vendor_name', models.CharField(blank=True, max_length=160)),
                ('destination_address', models.CharField(blank=True, max_length=255)),
                ('shopping_list', models.TextField(blank=True)),
                ('notes', models.TextField(blank=True)),
                ('status', models.CharField(choices=[('outbound', 'Traveling to vendor'), ('shopping', 'Purchasing materials'), ('returning', 'Returning to job'), ('completed', 'Returned to job'), ('canceled', 'Canceled')], default='outbound', max_length=20)),
                ('material_cost', models.DecimalField(decimal_places=2, default=0, max_digits=10)),
                ('mileage', models.DecimalField(decimal_places=2, default=0, max_digits=8)),
                ('receipt', models.FileField(blank=True, upload_to='material_receipts/%Y/%m/%d/')),
                ('started_at', models.DateTimeField(auto_now_add=True)),
                ('completed_at', models.DateTimeField(blank=True, null=True)),
                ('assignment', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='material_runs', to='fsm.jobassignment')),
                ('job', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='material_runs', to='fsm.job')),
                ('worker', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='material_runs', to='organizations.workerprofile')),
                ('workspace', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='material_runs', to='organizations.workspace')),
            ],
            options={'ordering': ('-started_at',)},
        ),
        migrations.CreateModel(
            name='WorkActivity',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('activity_type', models.CharField(choices=[('onsite_work', 'Onsite work'), ('material_travel_out', 'Material travel - outbound'), ('material_shopping', 'Purchasing materials'), ('material_travel_return', 'Material travel - return'), ('travel_to_job', 'Travel to job'), ('reassignment_travel', 'Travel after reassignment'), ('waiting', 'Waiting'), ('paid_break', 'Paid break'), ('unpaid_break', 'Unpaid break'), ('other', 'Other work')], max_length=30)),
                ('is_paid', models.BooleanField(default=True)),
                ('started_at', models.DateTimeField(default=django.utils.timezone.now)),
                ('ended_at', models.DateTimeField(blank=True, null=True)),
                ('start_lat', models.DecimalField(decimal_places=6, max_digits=9)),
                ('start_lng', models.DecimalField(decimal_places=6, max_digits=9)),
                ('start_accuracy', models.DecimalField(decimal_places=2, default=0, max_digits=8)),
                ('end_lat', models.DecimalField(blank=True, decimal_places=6, max_digits=9, null=True)),
                ('end_lng', models.DecimalField(blank=True, decimal_places=6, max_digits=9, null=True)),
                ('end_accuracy', models.DecimalField(decimal_places=2, default=0, max_digits=8)),
                ('note', models.TextField(blank=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('assignment', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='work_activities', to='fsm.jobassignment')),
                ('field_shift', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='work_activities', to='fsm.fieldshift')),
                ('job', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='work_activities', to='fsm.job')),
                ('material_run', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='activities', to='fsm.materialrun')),
                ('worker', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='work_activities', to='organizations.workerprofile')),
                ('workspace', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='work_activities', to='organizations.workspace')),
            ],
            options={'ordering': ('-started_at', '-id')},
        ),
        migrations.AddIndex(model_name='workactivity', index=models.Index(fields=['workspace', 'started_at'], name='fsm_activity_workspace_time')),
        migrations.AddIndex(model_name='workactivity', index=models.Index(fields=['worker', 'started_at'], name='fsm_activity_worker_time')),
        migrations.AddIndex(model_name='workactivity', index=models.Index(fields=['job', 'started_at'], name='fsm_activity_job_time')),
        migrations.RunPython(backfill_assignment_activities, migrations.RunPython.noop),
        migrations.AddConstraint(
            model_name='workactivity',
            constraint=models.UniqueConstraint(
                condition=models.Q(ended_at__isnull=True), fields=('worker',),
                name='fsm_one_open_activity_worker',
            ),
        ),
    ]

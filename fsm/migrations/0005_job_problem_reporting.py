import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('fsm', '0004_field_operations_workflow')]

    operations = [
        migrations.AlterField(
            model_name='fieldevent',
            name='event_type',
            field=models.CharField(choices=[('shift_started', 'Available for work'), ('shift_ended', 'Shift ended'), ('job_accepted', 'Job accepted'), ('arrived', 'Arrived at location'), ('work_started', 'Work started'), ('task_completed', 'Task completed'), ('note_added', 'Note added'), ('evidence_added', 'Evidence added'), ('problem_reported', 'Problem reported'), ('closeout_confirmed', 'Closeout confirmed'), ('job_completed', 'Job completed')], max_length=30),
        ),
        migrations.CreateModel(
            name='JobIssue',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('title', models.CharField(max_length=180)),
                ('description', models.TextField(blank=True)),
                ('voice_transcript', models.TextField(blank=True)),
                ('priority', models.CharField(choices=[('normal', 'Normal'), ('urgent', 'Urgent'), ('safety', 'Safety issue')], default='normal', max_length=20)),
                ('status', models.CharField(choices=[('open', 'Open'), ('acknowledged', 'Acknowledged'), ('resolved', 'Resolved')], default='open', max_length=20)),
                ('lat', models.DecimalField(decimal_places=6, max_digits=9)),
                ('lng', models.DecimalField(decimal_places=6, max_digits=9)),
                ('accuracy', models.DecimalField(decimal_places=2, default=0, max_digits=8)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('acknowledged_at', models.DateTimeField(blank=True, null=True)),
                ('resolved_at', models.DateTimeField(blank=True, null=True)),
                ('resolution_notes', models.TextField(blank=True)),
                ('assignment', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='issues', to='fsm.jobassignment')),
                ('job', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='issues', to='fsm.job')),
                ('worker', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='reported_job_issues', to='organizations.workerprofile')),
                ('workspace', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='job_issues', to='organizations.workspace')),
            ],
            options={'ordering': ('-created_at',)},
        ),
        migrations.CreateModel(
            name='JobIssueMedia',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('file', models.FileField(upload_to='job_issues/%Y/%m/%d/')),
                ('media_type', models.CharField(choices=[('photo', 'Photo'), ('video', 'Video'), ('audio', 'Audio')], max_length=10)),
                ('uploaded_at', models.DateTimeField(auto_now_add=True)),
                ('issue', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='media', to='fsm.jobissue')),
            ],
        ),
    ]

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


def backfill_skill_accounts(apps, schema_editor):
    Skill = apps.get_model('organizations', 'Skill')
    for skill in Skill.objects.select_related('workspace__customer_account'):
        if skill.workspace_id and skill.workspace.customer_account_id:
            skill.customer_account_id = skill.workspace.customer_account_id
            skill.save(update_fields=['customer_account'])


class Migration(migrations.Migration):
    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('organizations', '0007_backfill_legacy_account_teams'),
    ]

    operations = [
        migrations.AddField(model_name='customeraccountmember', name='drivers_license_required', field=models.BooleanField(default=False)),
        migrations.AddField(model_name='customeraccountmember', name='photo_required', field=models.BooleanField(default=False)),
        migrations.AddField(model_name='workerprofile', name='job_title', field=models.CharField(blank=True, max_length=120)),
        migrations.AddField(model_name='workerprofile', name='photo', field=models.ImageField(blank=True, null=True, upload_to='employee_profiles/%Y/%m/')),
        migrations.AddField(model_name='workerprofile', name='start_date', field=models.DateField(blank=True, null=True)),
        migrations.AddField(
            model_name='skill',
            name='customer_account',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name='team_skills', to='organizations.customeraccount'),
        ),
        migrations.AlterField(
            model_name='skill',
            name='workspace',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name='skills', to='organizations.workspace'),
        ),
        migrations.CreateModel(
            name='EmployeeDocumentRequirement',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('title', models.CharField(max_length=150)),
                ('document_type', models.CharField(choices=[('drivers_license', "Driver's license"), ('identity', 'Identity document'), ('certification', 'Certification / license'), ('tax', 'Tax form'), ('insurance', 'Insurance document'), ('other', 'Other')], default='other', max_length=30)),
                ('instructions', models.TextField(blank=True)),
                ('required_by_default', models.BooleanField(default=False)),
                ('is_active', models.BooleanField(default=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('account', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='document_requirements', to='organizations.customeraccount')),
            ],
            options={'db_table': 'workspaces_employeedocumentrequirement', 'ordering': ('title',)},
        ),
        migrations.CreateModel(
            name='EmployeeDocument',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('document_type', models.CharField(choices=[('drivers_license', "Driver's license"), ('identity', 'Identity document'), ('certification', 'Certification / license'), ('tax', 'Tax form'), ('insurance', 'Insurance document'), ('other', 'Other')], max_length=30)),
                ('title', models.CharField(max_length=150)),
                ('file', models.FileField(upload_to='employee_documents/%Y/%m/')),
                ('status', models.CharField(choices=[('pending', 'Pending review'), ('approved', 'Approved'), ('rejected', 'Needs replacement')], default='pending', max_length=20)),
                ('expiration_date', models.DateField(blank=True, null=True)),
                ('uploaded_at', models.DateTimeField(auto_now_add=True)),
                ('reviewed_at', models.DateTimeField(blank=True, null=True)),
                ('review_notes', models.TextField(blank=True)),
                ('account', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='employee_documents', to='organizations.customeraccount')),
                ('requirement', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='submissions', to='organizations.employeedocumentrequirement')),
                ('reviewed_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='reviewed_employee_documents', to=settings.AUTH_USER_MODEL)),
                ('user', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='employee_documents', to=settings.AUTH_USER_MODEL)),
            ],
            options={'db_table': 'workspaces_employeedocument', 'ordering': ('-uploaded_at',)},
        ),
        migrations.AddField(
            model_name='employeedocumentrequirement',
            name='requested_members',
            field=models.ManyToManyField(blank=True, related_name='document_requests', to='organizations.customeraccountmember'),
        ),
        migrations.RunPython(backfill_skill_accounts, migrations.RunPython.noop),
    ]

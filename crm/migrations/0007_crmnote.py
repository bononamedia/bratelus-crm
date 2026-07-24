from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('crm', '0006_crm_archive'),
        ('fsm', '0008_job_archive'),
        ('organizations', '0011_customeraccount_operating_mode'),
    ]

    operations = [
        migrations.CreateModel(
            name='CRMNote',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('target_type', models.CharField(choices=[('contact', 'Contact'), ('account', 'Account'), ('property', 'Property'), ('job', 'Job')], max_length=20)),
                ('category', models.CharField(choices=[('general', 'General'), ('service', 'Service'), ('access', 'Access'), ('billing', 'Billing'), ('safety', 'Safety')], default='general', max_length=20)),
                ('visibility', models.CharField(choices=[('internal', 'Internal only'), ('customer', 'Customer visible')], default='internal', max_length=20)),
                ('body', models.TextField()),
                ('created_at', models.DateTimeField(auto_now_add=True, db_index=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('account', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name='notes', to='crm.account')),
                ('author', models.ForeignKey(null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='crm_notes', to=settings.AUTH_USER_MODEL)),
                ('contact', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name='notes', to='crm.contact')),
                ('job', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name='notes', to='fsm.job')),
                ('property', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name='notes', to='crm.property')),
                ('workspace', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='crm_notes', to='organizations.workspace')),
            ],
            options={
                'ordering': ['-created_at', '-id'],
            },
        ),
        migrations.AddIndex(
            model_name='crmnote',
            index=models.Index(fields=['workspace', 'target_type', 'created_at'], name='crm_crmnote_workspa_f44661_idx'),
        ),
    ]

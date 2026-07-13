from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('organizations', '0001_initial'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='WorkspaceEmailDomain',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('domain', models.CharField(max_length=255)),
                ('is_verified', models.BooleanField(default=False)),
                ('verification_notes', models.TextField(blank=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('workspace', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='email_domains', to='organizations.workspace')),
            ],
            options={
                'db_table': 'workspaces_emaildomain',
                'ordering': ('domain',),
                'unique_together': {('workspace', 'domain')},
            },
        ),
        migrations.CreateModel(
            name='WorkspaceEmailConnection',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('display_name', models.CharField(max_length=150)),
                ('from_email', models.EmailField(max_length=254)),
                ('connection_type', models.CharField(choices=[('google_workspace', 'Google Workspace'), ('microsoft_365', 'Microsoft 365 / Exchange'), ('imap_smtp', 'IMAP + SMTP'), ('pop3_smtp', 'POP3 + SMTP'), ('exchange', 'Exchange Server')], default='imap_smtp', max_length=40)),
                ('status', models.CharField(choices=[('draft', 'Draft'), ('needs_auth', 'Needs Auth'), ('active', 'Active'), ('error', 'Error')], default='draft', max_length=20)),
                ('incoming_host', models.CharField(blank=True, max_length=255)),
                ('incoming_port', models.PositiveIntegerField(blank=True, null=True)),
                ('outgoing_host', models.CharField(blank=True, max_length=255)),
                ('outgoing_port', models.PositiveIntegerField(blank=True, null=True)),
                ('use_ssl', models.BooleanField(default=True)),
                ('username', models.CharField(blank=True, max_length=255)),
                ('secret_reference', models.CharField(blank=True, help_text='Reference to encrypted credentials or OAuth token storage.', max_length=255)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('created_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, to=settings.AUTH_USER_MODEL)),
                ('domain', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='connections', to='organizations.workspaceemaildomain')),
                ('workspace', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='email_connections', to='organizations.workspace')),
            ],
            options={
                'db_table': 'workspaces_emailconnection',
                'ordering': ('from_email',),
            },
        ),
    ]

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('organizations', '0004_workspace_roles_and_worker_profile'),
    ]

    operations = [
        migrations.CreateModel(
            name='UserPasskeyCredential',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('credential_id', models.BinaryField(unique=True)),
                ('public_key', models.BinaryField()),
                ('sign_count', models.PositiveBigIntegerField(default=0)),
                ('transports', models.JSONField(blank=True, default=list)),
                ('device_type', models.CharField(blank=True, max_length=40)),
                ('backed_up', models.BooleanField(default=False)),
                ('name', models.CharField(default='Face ID passkey', max_length=100)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('last_used_at', models.DateTimeField(blank=True, null=True)),
                ('user', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='passkey_credentials', to=settings.AUTH_USER_MODEL)),
            ],
            options={'db_table': 'workspaces_userpasskeycredential', 'ordering': ('-created_at',)},
        ),
    ]

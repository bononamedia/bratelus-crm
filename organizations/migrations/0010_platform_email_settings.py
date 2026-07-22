from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('organizations', '0009_user_email_verification'),
    ]

    operations = [
        migrations.CreateModel(
            name='PlatformEmailSettings',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('display_name', models.CharField(default='Bratelus Support', max_length=120)),
                ('from_email', models.EmailField(default='support@bratelus.com', max_length=254)),
                ('support_email', models.EmailField(default='support@bratelus.com', max_length=254)),
                ('smtp_host', models.CharField(max_length=255)),
                ('smtp_port', models.PositiveIntegerField(default=587)),
                ('smtp_username', models.CharField(max_length=255)),
                ('smtp_password_encrypted', models.TextField(blank=True, editable=False)),
                ('use_tls', models.BooleanField(default=True)),
                ('use_ssl', models.BooleanField(default=False)),
                ('is_active', models.BooleanField(default=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
            ],
            options={
                'verbose_name': 'Platform email settings',
                'verbose_name_plural': 'Platform email settings',
                'db_table': 'workspaces_platformemailsettings',
            },
        ),
    ]

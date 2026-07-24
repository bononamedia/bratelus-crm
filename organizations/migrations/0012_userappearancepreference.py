from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('organizations', '0011_customeraccount_operating_mode'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='UserAppearancePreference',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('theme', models.CharField(choices=[('blue', 'Ocean Blue'), ('night', 'Night'), ('red', 'Crimson'), ('yellow', 'Sunrise'), ('green', 'Evergreen'), ('bold', 'Bold')], default='blue', max_length=12)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('user', models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name='appearance_preference', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'db_table': 'workspaces_userappearancepreference',
            },
        ),
    ]

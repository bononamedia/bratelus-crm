from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('organizations', '0010_platform_email_settings'),
    ]

    operations = [
        migrations.AddField(
            model_name='customeraccount',
            name='operating_mode',
            field=models.CharField(
                choices=[('solo', 'Solo'), ('team', 'Team')],
                default='team',
                max_length=10,
            ),
            preserve_default=False,
        ),
        migrations.AlterField(
            model_name='customeraccount',
            name='operating_mode',
            field=models.CharField(
                choices=[('solo', 'Solo'), ('team', 'Team')],
                default='solo',
                max_length=10,
            ),
        ),
    ]

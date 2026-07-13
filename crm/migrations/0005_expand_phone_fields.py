from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('crm', '0004_zoho_compatible_contacts_and_accounts'),
    ]

    operations = [
        migrations.AlterField(
            model_name='account',
            name='phone',
            field=models.CharField(blank=True, max_length=50),
        ),
        migrations.AlterField(
            model_name='contact',
            name='phone',
            field=models.CharField(blank=True, max_length=50),
        ),
        migrations.AlterField(
            model_name='contact',
            name='mobile',
            field=models.CharField(blank=True, max_length=50),
        ),
    ]

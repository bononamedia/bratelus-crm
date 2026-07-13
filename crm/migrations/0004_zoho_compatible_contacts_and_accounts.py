from django.db import migrations, models
import django.db.models.deletion


def backfill_contact_workspace(apps, schema_editor):
    Contact = apps.get_model('crm', 'Contact')
    for contact in Contact.objects.select_related('account').all().iterator():
        if contact.account_id:
            contact.organization_id = contact.account.organization_id
            contact.save(update_fields=['organization'])


class Migration(migrations.Migration):
    dependencies = [
        ('crm', '0003_property_unit_number_alter_property_address'),
        ('organizations', '0003_workspace_created_by'),
    ]

    operations = [
        migrations.AddField(model_name='account', name='email', field=models.EmailField(blank=True, max_length=254)),
        migrations.AddField(model_name='account', name='website', field=models.URLField(blank=True)),
        migrations.AddField(model_name='account', name='billing_street', field=models.CharField(blank=True, max_length=255)),
        migrations.AddField(model_name='account', name='billing_city', field=models.CharField(blank=True, max_length=100)),
        migrations.AddField(model_name='account', name='billing_state', field=models.CharField(blank=True, max_length=100)),
        migrations.AddField(model_name='account', name='billing_postal_code', field=models.CharField(blank=True, max_length=20)),
        migrations.AddField(model_name='account', name='billing_country', field=models.CharField(blank=True, default='United States', max_length=100)),
        migrations.AddField(model_name='account', name='shipping_street', field=models.CharField(blank=True, max_length=255)),
        migrations.AddField(model_name='account', name='shipping_city', field=models.CharField(blank=True, max_length=100)),
        migrations.AddField(model_name='account', name='shipping_state', field=models.CharField(blank=True, max_length=100)),
        migrations.AddField(model_name='account', name='shipping_postal_code', field=models.CharField(blank=True, max_length=20)),
        migrations.AddField(model_name='account', name='shipping_country', field=models.CharField(blank=True, max_length=100)),
        migrations.AddField(
            model_name='contact',
            name='organization',
            field=models.ForeignKey(null=True, on_delete=django.db.models.deletion.CASCADE, related_name='contacts', to='organizations.workspace'),
        ),
        migrations.AlterField(
            model_name='contact',
            name='account',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='contacts', to='crm.account'),
        ),
        migrations.AlterField(model_name='contact', name='email', field=models.EmailField(blank=True, max_length=254)),
        migrations.AddField(model_name='contact', name='secondary_email', field=models.EmailField(blank=True, max_length=254)),
        migrations.AddField(model_name='contact', name='mobile', field=models.CharField(blank=True, max_length=20)),
        migrations.AddField(model_name='contact', name='mailing_street', field=models.CharField(blank=True, max_length=255)),
        migrations.AddField(model_name='contact', name='mailing_city', field=models.CharField(blank=True, max_length=100)),
        migrations.AddField(model_name='contact', name='mailing_state', field=models.CharField(blank=True, max_length=100)),
        migrations.AddField(model_name='contact', name='mailing_postal_code', field=models.CharField(blank=True, max_length=20)),
        migrations.AddField(model_name='contact', name='mailing_country', field=models.CharField(blank=True, max_length=100)),
        migrations.AddField(model_name='contact', name='lead_source', field=models.CharField(blank=True, max_length=100)),
        migrations.AddField(model_name='contact', name='status', field=models.CharField(blank=True, max_length=100)),
        migrations.AddField(model_name='contact', name='description', field=models.TextField(blank=True)),
        migrations.AddField(model_name='contact', name='email_opt_out', field=models.BooleanField(default=False)),
        migrations.AddField(model_name='contact', name='sms_opt_out', field=models.BooleanField(default=False)),
        migrations.AddField(model_name='contact', name='external_source', field=models.CharField(blank=True, max_length=50)),
        migrations.AddField(model_name='contact', name='external_id', field=models.CharField(blank=True, max_length=100)),
        migrations.AddField(model_name='contact', name='created_at', field=models.DateTimeField(auto_now_add=True)),
        migrations.AddField(model_name='contact', name='updated_at', field=models.DateTimeField(auto_now=True)),
        migrations.RunPython(backfill_contact_workspace, migrations.RunPython.noop),
        migrations.AlterField(
            model_name='contact',
            name='organization',
            field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='contacts', to='organizations.workspace'),
        ),
        migrations.AddConstraint(
            model_name='contact',
            constraint=models.UniqueConstraint(
                condition=~models.Q(external_id=''),
                fields=('organization', 'external_source', 'external_id'),
                name='crm_contact_unique_external_record',
            ),
        ),
    ]

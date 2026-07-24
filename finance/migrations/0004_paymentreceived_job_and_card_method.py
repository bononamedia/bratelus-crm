from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('finance', '0003_invoice_amount_paid_invoice_contact_and_more'),
        ('fsm', '0007_jobtask_assigned_worker'),
    ]

    operations = [
        migrations.AddField(
            model_name='paymentreceived',
            name='job',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='payments_received',
                to='fsm.job',
            ),
        ),
        migrations.AlterField(
            model_name='paymentreceived',
            name='method',
            field=models.CharField(
                choices=[
                    ('card', 'Credit / debit card'),
                    ('stripe', 'Stripe'),
                    ('paypal', 'PayPal'),
                    ('paysimple', 'PaySimple'),
                    ('zelle', 'Zelle'),
                    ('pix', 'PIX'),
                    ('check', 'Check'),
                    ('cash', 'Cash'),
                    ('bank_transfer', 'Bank transfer'),
                    ('other', 'Other'),
                ],
                max_length=30,
            ),
        ),
        migrations.AlterField(
            model_name='workspacepaymentoption',
            name='method',
            field=models.CharField(
                choices=[
                    ('card', 'Credit / debit card'),
                    ('stripe', 'Stripe'),
                    ('paypal', 'PayPal'),
                    ('paysimple', 'PaySimple'),
                    ('zelle', 'Zelle'),
                    ('pix', 'PIX'),
                    ('check', 'Check'),
                    ('cash', 'Cash'),
                    ('bank_transfer', 'Bank transfer'),
                    ('other', 'Other'),
                ],
                max_length=30,
            ),
        ),
    ]

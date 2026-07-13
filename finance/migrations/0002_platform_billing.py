from decimal import Decimal

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


def seed_bratelus_plan(apps, schema_editor):
    Plan = apps.get_model('finance', 'SubscriptionPlan')
    Tier = apps.get_model('finance', 'SeatPricingTier')
    plan, _ = Plan.objects.get_or_create(
        code='full-crm',
        defaults={
            'name': 'Bratelus Full CRM',
            'description': 'Full CRM, dispatch, workforce, finance, and reporting for one workspace.',
            'base_monthly_amount': Decimal('49.00'),
            'included_users': 1,
            'currency': 'usd',
        },
    )
    tiers = [
        (1, 5, Decimal('25.00'), 1),
        (6, 10, Decimal('20.00'), 2),
        (11, 50, Decimal('15.00'), 3),
        (51, None, Decimal('10.00'), 4),
    ]
    for first_seat, up_to_seat, unit_amount, sort_order in tiers:
        Tier.objects.get_or_create(
            plan=plan,
            first_seat=first_seat,
            defaults={'up_to_seat': up_to_seat, 'unit_amount': unit_amount, 'sort_order': sort_order},
        )


class Migration(migrations.Migration):
    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('finance', '0001_initial'),
        ('organizations', '0003_workspace_created_by'),
    ]

    operations = [
        migrations.CreateModel(
            name='SubscriptionPlan',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=100)),
                ('code', models.SlugField(unique=True)),
                ('description', models.TextField(blank=True)),
                ('base_monthly_amount', models.DecimalField(decimal_places=2, default=49, max_digits=10)),
                ('included_users', models.PositiveIntegerField(default=1)),
                ('currency', models.CharField(default='usd', max_length=3)),
                ('is_active', models.BooleanField(default=True)),
                ('stripe_base_price_id', models.CharField(blank=True, max_length=100)),
                ('stripe_seat_price_id', models.CharField(blank=True, max_length=100)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
            ],
            options={'ordering': ('base_monthly_amount', 'name')},
        ),
        migrations.CreateModel(
            name='WorkspaceSubscription',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('billing_email', models.EmailField(blank=True, max_length=254)),
                ('seat_count', models.PositiveIntegerField(default=1)),
                ('status', models.CharField(choices=[('trialing', 'Trialing'), ('active', 'Active'), ('past_due', 'Past due'), ('canceled', 'Canceled'), ('incomplete', 'Incomplete'), ('unpaid', 'Unpaid')], default='trialing', max_length=20)),
                ('stripe_customer_id', models.CharField(blank=True, db_index=True, max_length=100)),
                ('stripe_subscription_id', models.CharField(blank=True, db_index=True, max_length=100)),
                ('stripe_seat_item_id', models.CharField(blank=True, max_length=100)),
                ('current_period_start', models.DateTimeField(blank=True, null=True)),
                ('current_period_end', models.DateTimeField(blank=True, null=True)),
                ('cancel_at_period_end', models.BooleanField(default=False)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('plan', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='subscriptions', to='finance.subscriptionplan')),
                ('workspace', models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name='subscription', to='organizations.workspace')),
            ],
        ),
        migrations.CreateModel(
            name='SeatPricingTier',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('first_seat', models.PositiveIntegerField()),
                ('up_to_seat', models.PositiveIntegerField(blank=True, null=True)),
                ('unit_amount', models.DecimalField(decimal_places=2, max_digits=10)),
                ('sort_order', models.PositiveIntegerField(default=0)),
                ('plan', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='seat_tiers', to='finance.subscriptionplan')),
            ],
            options={'ordering': ('sort_order', 'first_seat'), 'unique_together': {('plan', 'first_seat')}},
        ),
        migrations.CreateModel(
            name='PlatformInvoice',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('stripe_invoice_id', models.CharField(max_length=100, unique=True)),
                ('invoice_number', models.CharField(blank=True, max_length=100)),
                ('status', models.CharField(blank=True, max_length=30)),
                ('currency', models.CharField(default='usd', max_length=3)),
                ('amount_due', models.DecimalField(decimal_places=2, default=0, max_digits=12)),
                ('amount_paid', models.DecimalField(decimal_places=2, default=0, max_digits=12)),
                ('hosted_invoice_url', models.URLField(blank=True)),
                ('invoice_pdf_url', models.URLField(blank=True)),
                ('period_start', models.DateTimeField(blank=True, null=True)),
                ('period_end', models.DateTimeField(blank=True, null=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('subscription', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='invoices', to='finance.workspacesubscription')),
                ('workspace', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='platform_invoices', to='organizations.workspace')),
            ],
            options={'ordering': ('-created_at',)},
        ),
        migrations.CreateModel(
            name='BillingEvent',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('event_type', models.CharField(max_length=100)),
                ('stripe_event_id', models.CharField(blank=True, max_length=100, null=True, unique=True)),
                ('summary', models.CharField(max_length=255)),
                ('metadata', models.JSONField(blank=True, default=dict)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('actor', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, to=settings.AUTH_USER_MODEL)),
                ('workspace', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name='billing_events', to='organizations.workspace')),
            ],
            options={'ordering': ('-created_at',)},
        ),
        migrations.RunPython(seed_bratelus_plan, migrations.RunPython.noop),
    ]

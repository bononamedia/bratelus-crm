from django.db import models
from django.conf import settings
from organizations.models import Workspace
from crm.models.contacts import Account
from fsm.models import Job

class Invoice(models.Model):
    """The master bill sent to the Account"""
    STATUS_CHOICES = [
        ('draft', 'Draft'),
        ('sent', 'Sent'),
        ('paid', 'Paid'),
        ('overdue', 'Overdue'),
        ('canceled', 'Canceled')
    ]

    # CHANGED: Renamed the database column from workspace to organization
    organization = models.ForeignKey(Workspace, on_delete=models.CASCADE, related_name='invoices')
    account = models.ForeignKey(Account, on_delete=models.CASCADE, related_name='invoices')
    
    invoice_number = models.CharField(max_length=50, unique=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='draft')
    
    issue_date = models.DateField(auto_now_add=True)
    due_date = models.DateField()
    
    # Financial Totals
    subtotal = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)
    tax_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)
    total_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)
    
    # The PaaS Custom Data Bucket (e.g., for Custom "PO Numbers" or "Tax IDs")
    custom_data = models.JSONField(default=dict, blank=True)

    def __str__(self):
        return f"Invoice {self.invoice_number} - {self.account.name}"

class LineItem(models.Model):
    """The individual charges on the invoice"""
    invoice = models.ForeignKey(Invoice, on_delete=models.CASCADE, related_name='line_items')
    
    # THE MAGIC LINK: If this charge came from a specific job, it links here!
    job = models.ForeignKey(Job, on_delete=models.SET_NULL, null=True, blank=True, related_name='invoiced_items')
    
    description = models.CharField(max_length=255)
    quantity = models.DecimalField(max_digits=8, decimal_places=2, default=1.00)
    unit_price = models.DecimalField(max_digits=10, decimal_places=2)
    total_price = models.DecimalField(max_digits=10, decimal_places=2)

    def save(self, *args, **kwargs):
        # Auto-calculate the total price before saving
        self.total_price = self.quantity * self.unit_price
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.description} ({self.quantity} x ${self.unit_price})"


class SubscriptionPlan(models.Model):
    """A platform package managed by the Bratelus superadmin."""

    name = models.CharField(max_length=100)
    code = models.SlugField(unique=True)
    description = models.TextField(blank=True)
    base_monthly_amount = models.DecimalField(max_digits=10, decimal_places=2, default=49)
    included_users = models.PositiveIntegerField(default=1)
    currency = models.CharField(max_length=3, default='usd')
    is_active = models.BooleanField(default=True)
    stripe_base_price_id = models.CharField(max_length=100, blank=True)
    stripe_seat_price_id = models.CharField(max_length=100, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ('base_monthly_amount', 'name')

    def __str__(self):
        return self.name


class SeatPricingTier(models.Model):
    """Graduated pricing for additional users beyond the included seats."""

    plan = models.ForeignKey(SubscriptionPlan, on_delete=models.CASCADE, related_name='seat_tiers')
    first_seat = models.PositiveIntegerField()
    up_to_seat = models.PositiveIntegerField(null=True, blank=True)
    unit_amount = models.DecimalField(max_digits=10, decimal_places=2)
    sort_order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ('sort_order', 'first_seat')
        unique_together = ('plan', 'first_seat')

    def __str__(self):
        ceiling = self.up_to_seat or 'plus'
        return f'{self.plan.name}: seats {self.first_seat}-{ceiling}'


class WorkspaceSubscription(models.Model):
    STATUS_CHOICES = [
        ('trialing', 'Trialing'),
        ('active', 'Active'),
        ('past_due', 'Past due'),
        ('canceled', 'Canceled'),
        ('incomplete', 'Incomplete'),
        ('unpaid', 'Unpaid'),
    ]

    workspace = models.OneToOneField(Workspace, on_delete=models.CASCADE, related_name='subscription')
    plan = models.ForeignKey(SubscriptionPlan, on_delete=models.PROTECT, related_name='subscriptions')
    billing_email = models.EmailField(blank=True)
    seat_count = models.PositiveIntegerField(default=1)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='trialing')
    stripe_customer_id = models.CharField(max_length=100, blank=True, db_index=True)
    stripe_subscription_id = models.CharField(max_length=100, blank=True, db_index=True)
    stripe_seat_item_id = models.CharField(max_length=100, blank=True)
    current_period_start = models.DateTimeField(null=True, blank=True)
    current_period_end = models.DateTimeField(null=True, blank=True)
    cancel_at_period_end = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f'{self.workspace.name} / {self.plan.name}'


class PlatformInvoice(models.Model):
    workspace = models.ForeignKey(Workspace, on_delete=models.CASCADE, related_name='platform_invoices')
    subscription = models.ForeignKey(
        WorkspaceSubscription,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='invoices',
    )
    stripe_invoice_id = models.CharField(max_length=100, unique=True)
    invoice_number = models.CharField(max_length=100, blank=True)
    status = models.CharField(max_length=30, blank=True)
    currency = models.CharField(max_length=3, default='usd')
    amount_due = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    amount_paid = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    hosted_invoice_url = models.URLField(blank=True)
    invoice_pdf_url = models.URLField(blank=True)
    period_start = models.DateTimeField(null=True, blank=True)
    period_end = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ('-created_at',)

    def __str__(self):
        return self.invoice_number or self.stripe_invoice_id


class BillingEvent(models.Model):
    workspace = models.ForeignKey(
        Workspace,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='billing_events',
    )
    event_type = models.CharField(max_length=100)
    stripe_event_id = models.CharField(max_length=100, blank=True, unique=True, null=True)
    summary = models.CharField(max_length=255)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ('-created_at',)

    def __str__(self):
        return self.summary

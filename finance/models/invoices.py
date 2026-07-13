from django.db import models
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
import requests
from django.db import models
from organizations.models import Workspace

# ==========================================
# 1 - ACCOUNT & ORGANIZATION
# ==========================================

class Account(models.Model):
    """
    The top-level entity representing a Client or Business.
    All properties, contacts, and jobs roll up to an Account.
    """
    organization = models.ForeignKey(Workspace, on_delete=models.CASCADE, related_name='accounts')
    name = models.CharField(max_length=255)
    phone = models.CharField(max_length=50, blank=True)
    email = models.EmailField(blank=True)
    website = models.URLField(blank=True)
    billing_address = models.TextField(blank=True)
    billing_street = models.CharField(max_length=255, blank=True)
    billing_city = models.CharField(max_length=100, blank=True)
    billing_state = models.CharField(max_length=100, blank=True)
    billing_postal_code = models.CharField(max_length=20, blank=True)
    billing_country = models.CharField(max_length=100, blank=True, default='United States')
    shipping_street = models.CharField(max_length=255, blank=True)
    shipping_city = models.CharField(max_length=100, blank=True)
    shipping_state = models.CharField(max_length=100, blank=True)
    shipping_postal_code = models.CharField(max_length=20, blank=True)
    shipping_country = models.CharField(max_length=100, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    
    # The bucket for infinite custom fields
    custom_data = models.JSONField(default=dict, blank=True)

    def __str__(self):
        return self.name


# ==========================================
# 2 - CONTACTS & PERSONNEL
# ==========================================

class Contact(models.Model):
    """
    Individual people associated with an Account.
    """
    organization = models.ForeignKey(Workspace, on_delete=models.CASCADE, related_name='contacts')
    account = models.ForeignKey(
        Account,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='contacts',
    )
    first_name = models.CharField(max_length=100)
    last_name = models.CharField(max_length=100)
    email = models.EmailField(blank=True)
    secondary_email = models.EmailField(blank=True)
    phone = models.CharField(max_length=50, blank=True)
    mobile = models.CharField(max_length=50, blank=True)
    mailing_street = models.CharField(max_length=255, blank=True)
    mailing_city = models.CharField(max_length=100, blank=True)
    mailing_state = models.CharField(max_length=100, blank=True)
    mailing_postal_code = models.CharField(max_length=20, blank=True)
    mailing_country = models.CharField(max_length=100, blank=True)
    lead_source = models.CharField(max_length=100, blank=True)
    status = models.CharField(max_length=100, blank=True)
    description = models.TextField(blank=True)
    email_opt_out = models.BooleanField(default=False)
    sms_opt_out = models.BooleanField(default=False)
    external_source = models.CharField(max_length=50, blank=True)
    external_id = models.CharField(max_length=100, blank=True)
    is_primary = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    # The bucket for infinite custom fields
    custom_data = models.JSONField(default=dict, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=('organization', 'external_source', 'external_id'),
                condition=~models.Q(external_id=''),
                name='crm_contact_unique_external_record',
            ),
        ]

    def __str__(self):
        return f"{self.first_name} {self.last_name}"


# ==========================================
# 3 - PROPERTIES & GEO-ROUTING
# ==========================================

class Property(models.Model):
    """
    The physical location where jobs take place (Belongs to an Account).
    Includes auto-geocoding via OpenStreetMap for dispatch routing.
    """
    account = models.ForeignKey(Account, on_delete=models.CASCADE, related_name='properties')
    name = models.CharField(max_length=255) 
    
    # NEW: Split the address and unit number
    address = models.CharField(max_length=255, help_text="Street address, city, state (e.g., 1170 N Federal Hwy, Fort Lauderdale, FL)")
    unit_number = models.CharField(max_length=50, blank=True, help_text="Apt, Suite, Unit, or Building number")
    
    # Access details
    gate_code = models.CharField(max_length=50, blank=True)
    
    # Geolocation for the Distance Matrix API
    location_lat = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    location_lng = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    
    # The bucket for infinite custom fields
    custom_data = models.JSONField(default=dict, blank=True)

    def save(self, *args, **kwargs):
        """
        Overrides the standard save method. 
        If an address is provided but no GPS coordinates exist, it quietly
        calls the OpenStreetMap API to fetch the Lat/Lng before saving.
        """
        if self.address and not self.location_lat and not self.location_lng:
            try:
                headers = {'User-Agent': 'BratelusCRM/1.0'} 
                url = f"https://nominatim.openstreetmap.org/search?q={self.address}&format=json&limit=1"
                
                response = requests.get(url, headers=headers, timeout=5)
                
                if response.status_code == 200:
                    data = response.json()
                    if data: 
                        self.location_lat = data[0]['lat']
                        self.location_lng = data[0]['lon']
            except Exception as e:
                print(f"Geocoding failed: {e}")
                pass 

        super().save(*args, **kwargs)

    def __str__(self):
        if self.unit_number:
            return f"{self.name} ({self.address} - Unit {self.unit_number})"
        return f"{self.name} ({self.address})"


# ==========================================
# 4 - FINANCIAL ROUTING
# ==========================================

class PaymentMethod(models.Model):
    """
    Acts as the financial routing engine. 
    Links a client to a tokenized payment method.
    """
    account = models.ForeignKey(Account, on_delete=models.CASCADE, related_name='payment_methods')
    
    # Is this the default card for all general billing?
    is_default = models.BooleanField(default=False)
    
    # Optional routing: Is this card specifically restricted to a single property?
    assigned_property = models.ForeignKey(Property, on_delete=models.SET_NULL, null=True, blank=True, related_name='assigned_cards')
    
    # Basic tokenization info (NEVER store full CC numbers in the DB)
    card_type = models.CharField(max_length=50, blank=True) # e.g., 'Visa', 'Mastercard'
    last_four = models.CharField(max_length=4)
    processor_token = models.CharField(max_length=255, blank=True, help_text="The token from Stripe/Authorize.net")
    expiration_date = models.CharField(max_length=7, blank=True, help_text="MM/YYYY")

    class Meta:
        verbose_name_plural = "Payment Methods"
        
    def __str__(self):
        return f"{self.card_type} ending in {self.last_four} ({self.account.name})"

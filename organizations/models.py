from django.db import models
from django.contrib.auth.models import User
import uuid

# ---------------------------------------------------------
# CORE TENANT MODELS
# ---------------------------------------------------------
class CustomerAccount(models.Model):
    """The paying Bratelus customer that owns one or more workspace brands."""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=255)
    owner = models.ForeignKey(User, on_delete=models.PROTECT, related_name='owned_customer_accounts')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'workspaces_customeraccount'

    def __str__(self):
        return self.name


class CustomerAccountMember(models.Model):
    ROLE_CHOICES = [
        ('owner', 'Owner'),
        ('admin', 'Administrator'),
        ('manager', 'Manager'),
        ('employee', 'Employee'),
    ]

    account = models.ForeignKey(CustomerAccount, on_delete=models.CASCADE, related_name='members')
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='customer_accounts')
    role = models.CharField(max_length=20, choices=ROLE_CHOICES, default='employee')
    can_work_jobs = models.BooleanField(default=False)
    can_view_billing = models.BooleanField(default=False)
    photo_required = models.BooleanField(default=False)
    drivers_license_required = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = 'workspaces_customeraccountmember'
        unique_together = ('account', 'user')

    def __str__(self):
        return f'{self.user} / {self.account} ({self.role})'


class Workspace(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=255)
    slug = models.SlugField(unique=True)
    customer_account = models.ForeignKey(
        CustomerAccount,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='workspaces',
    )
    calendar_color = models.CharField(max_length=7, default='#2563eb')
    created_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='created_workspaces',
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'workspaces_workspace'

    def __str__(self):
        return self.name

class WorkspaceMember(models.Model):
    ROLE_CHOICES = [
        ('admin', 'Admin'),
        ('manager', 'Manager'),
        ('employee', 'Employee'),
        ('field_worker', 'Field Work'),
    ]
    
    workspace = models.ForeignKey(Workspace, on_delete=models.CASCADE, related_name='members')
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='workspaces')
    role = models.CharField(max_length=20, choices=ROLE_CHOICES, default='field_worker')
    is_active = models.BooleanField(default=True)
    can_view_billing = models.BooleanField(default=False)

    class Meta:
        db_table = 'workspaces_workspacemember'

    def __str__(self):
        return f"{self.user.username} - {self.workspace.name} ({self.role})"


class UserPasskeyCredential(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='passkey_credentials')
    credential_id = models.BinaryField(unique=True)
    public_key = models.BinaryField()
    sign_count = models.PositiveBigIntegerField(default=0)
    transports = models.JSONField(default=list, blank=True)
    device_type = models.CharField(max_length=40, blank=True)
    backed_up = models.BooleanField(default=False)
    name = models.CharField(max_length=100, default='Face ID passkey')
    created_at = models.DateTimeField(auto_now_add=True)
    last_used_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = 'workspaces_userpasskeycredential'
        ordering = ('-created_at',)


class UserEmailVerification(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='email_verification')
    sent_at = models.DateTimeField(null=True, blank=True)
    verified_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = 'workspaces_useremailverification'

    @property
    def is_verified(self):
        return self.verified_at is not None


class PlatformEmailSettings(models.Model):
    """Singleton SMTP configuration for Bratelus-owned transactional email."""

    display_name = models.CharField(max_length=120, default='Bratelus Support')
    from_email = models.EmailField(default='support@bratelus.com')
    support_email = models.EmailField(default='support@bratelus.com')
    smtp_host = models.CharField(max_length=255)
    smtp_port = models.PositiveIntegerField(default=587)
    smtp_username = models.CharField(max_length=255)
    smtp_password_encrypted = models.TextField(blank=True, editable=False)
    use_tls = models.BooleanField(default=True)
    use_ssl = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'workspaces_platformemailsettings'
        verbose_name = 'Platform email settings'
        verbose_name_plural = 'Platform email settings'

    def clean(self):
        from django.core.exceptions import ValidationError

        super().clean()
        if self.use_tls and self.use_ssl:
            raise ValidationError('Choose TLS or SSL, not both.')

    def save(self, *args, **kwargs):
        self.pk = 1
        super().save(*args, **kwargs)

    def set_smtp_password(self, password):
        from .secrets import encrypt_secret

        self.smtp_password_encrypted = encrypt_secret(password) if password else ''

    def get_smtp_password(self):
        from .secrets import decrypt_secret

        return decrypt_secret(self.smtp_password_encrypted) if self.smtp_password_encrypted else ''

    @property
    def password_configured(self):
        return bool(self.smtp_password_encrypted)

    def __str__(self):
        return f'{self.display_name} <{self.from_email}>'


# ---------------------------------------------------------
# WORKSPACE CHANNELS (EMAIL / DOMAIN SETUP)
# ---------------------------------------------------------
class WorkspaceEmailDomain(models.Model):
    """A verified sending domain owned by a workspace brand."""
    workspace = models.ForeignKey(Workspace, on_delete=models.CASCADE, related_name='email_domains')
    domain = models.CharField(max_length=255)
    is_verified = models.BooleanField(default=False)
    verification_notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'workspaces_emaildomain'
        unique_together = ('workspace', 'domain')
        ordering = ('domain',)

    def __str__(self):
        return f"{self.domain} ({self.workspace.name})"


class WorkspaceEmailConnection(models.Model):
    """Mailbox or provider connection configured at the workspace level."""
    CONNECTION_TYPES = [
        ('google_workspace', 'Google Workspace'),
        ('microsoft_365', 'Microsoft 365 / Exchange'),
        ('imap_smtp', 'IMAP + SMTP'),
        ('pop3_smtp', 'POP3 + SMTP'),
        ('exchange', 'Exchange Server'),
    ]
    STATUS_CHOICES = [
        ('draft', 'Draft'),
        ('needs_auth', 'Needs Auth'),
        ('active', 'Active'),
        ('error', 'Error'),
    ]

    workspace = models.ForeignKey(Workspace, on_delete=models.CASCADE, related_name='email_connections')
    domain = models.ForeignKey(
        WorkspaceEmailDomain,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='connections',
    )
    display_name = models.CharField(max_length=150)
    from_email = models.EmailField()
    connection_type = models.CharField(max_length=40, choices=CONNECTION_TYPES, default='imap_smtp')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='draft')
    incoming_host = models.CharField(max_length=255, blank=True)
    incoming_port = models.PositiveIntegerField(null=True, blank=True)
    outgoing_host = models.CharField(max_length=255, blank=True)
    outgoing_port = models.PositiveIntegerField(null=True, blank=True)
    use_ssl = models.BooleanField(default=True)
    username = models.CharField(max_length=255, blank=True)
    secret_reference = models.CharField(
        max_length=255,
        blank=True,
        help_text='Reference to encrypted credentials or OAuth token storage.',
    )
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'workspaces_emailconnection'
        ordering = ('from_email',)

    def __str__(self):
        return f"{self.from_email} ({self.workspace.name})"


# ---------------------------------------------------------
# THE WORKFORCE ENGINE
# ---------------------------------------------------------
class WorkerProfile(models.Model):
    EMPLOYMENT_TYPE_CHOICES = [
        ('1099', '1099 Contractor'),
        ('w2', 'W-2 Employee'),
        ('other', 'Other'),
    ]

    user = models.OneToOneField(User, on_delete=models.CASCADE)
    # Changed to ManyToMany so a user can belong to multiple organizations!
    workspaces = models.ManyToManyField(Workspace, related_name='workers')
    
    phone = models.CharField(max_length=20, blank=True)
    photo = models.ImageField(upload_to='employee_profiles/%Y/%m/', null=True, blank=True)
    job_title = models.CharField(max_length=120, blank=True)
    start_date = models.DateField(null=True, blank=True)
    is_admin = models.BooleanField(default=False)
    employment_type = models.CharField(max_length=20, choices=EMPLOYMENT_TYPE_CHOICES, blank=True)
    home_street = models.CharField(max_length=255, blank=True)
    home_city = models.CharField(max_length=100, blank=True)
    home_state = models.CharField(max_length=100, blank=True)
    home_postal_code = models.CharField(max_length=20, blank=True)
    home_country = models.CharField(max_length=100, blank=True, default='United States')
    emergency_contact_name = models.CharField(max_length=150, blank=True)
    emergency_contact_phone = models.CharField(max_length=30, blank=True)
    current_balance = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    next_payment_date = models.DateField(null=True, blank=True)

    class Meta:
        db_table = 'workspaces_workerprofile'

    def __str__(self):
        return f"{self.user.get_full_name()} Profile"

# ---------------------------------------------------------
# THE CUSTOM FIELD BUILDER
# ---------------------------------------------------------
class CustomField(models.Model):
    """Defines a custom field created by a Tenant Admin"""
    FIELD_TYPES = [
        ('text', 'Short Text'),
        ('textarea', 'Paragraph'),
        ('number', 'Number'),
        ('date', 'Date'),
        ('dropdown', 'Dropdown List'),
        ('boolean', 'Checkbox')
    ]
    
    workspace = models.ForeignKey(Workspace, on_delete=models.CASCADE, related_name='custom_fields')
    target_model = models.CharField(max_length=50) 
    
    label = models.CharField(max_length=100)           
    internal_name = models.CharField(max_length=100)   
    field_type = models.CharField(max_length=20, choices=FIELD_TYPES)
    
    options = models.JSONField(default=list, blank=True)
    is_required = models.BooleanField(default=False)

    class Meta:
        db_table = 'workspaces_customfield'

    def __str__(self):
        return f"{self.target_model} -> {self.label}"


# ---------------------------------------------------------
# THE FORM LAYOUT ENGINE
# ---------------------------------------------------------
class FormLayout(models.Model):
    """Stores the drag-and-drop form layout for a specific model"""
    workspace = models.ForeignKey(Workspace, on_delete=models.CASCADE, related_name='form_layouts')
    target_model = models.CharField(max_length=50) 
    
    layout_json = models.JSONField(default=list)

    class Meta:
        db_table = 'workspaces_formlayout'

    def __str__(self):
        return f"{self.workspace.name} - {self.target_model} Form"


# ---------------------------------------------------------
# THE DASHBOARD ENGINE
# ---------------------------------------------------------
class DashboardWidget(models.Model):
    """Stores the size and position of widgets on a user's dashboard"""
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='dashboard_widgets')
    
    widget_type = models.CharField(max_length=50)
    
    width = models.IntegerField(default=2)
    height = models.IntegerField(default=2)
    x_position = models.IntegerField(default=0)
    y_position = models.IntegerField(default=0)
    
    settings = models.JSONField(default=dict, blank=True)

    class Meta:
        db_table = 'workspaces_dashboardwidget'

    def __str__(self):
        return f"{self.user.username} - {self.widget_type}"
    
# ---------------------------------------------------------
# THE FSM ROUTING ENGINE (SKILLS & TERRITORIES)
# ---------------------------------------------------------
class Skill(models.Model):
    """The master list of services a tenant offers (e.g., 'Window Cleaning')"""
    customer_account = models.ForeignKey(
        CustomerAccount,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='team_skills',
    )
    workspace = models.ForeignKey(Workspace, on_delete=models.CASCADE, null=True, blank=True, related_name='skills')
    name = models.CharField(max_length=100)
    description = models.TextField(blank=True)

    class Meta:
        db_table = 'workspaces_skill'

    def __str__(self):
        owner = self.customer_account or self.workspace
        return f"{self.name} ({owner})"

class WorkerSkill(models.Model):
    """Maps a worker to a skill with a specific proficiency level"""
    PROFICIENCY_CHOICES = [
        (1, 'Trainee / Helper'),
        (2, 'Secondary / Competent'),
        (3, 'Primary / Expert')
    ]
    
    worker = models.ForeignKey('WorkerProfile', on_delete=models.CASCADE, related_name='skills')
    skill = models.ForeignKey(Skill, on_delete=models.CASCADE, related_name='qualified_workers')
    proficiency_level = models.IntegerField(choices=PROFICIENCY_CHOICES, default=3)

    class Meta:
        db_table = 'workspaces_workerskill'
        unique_together = ('worker', 'skill') # A worker can't have the same skill listed twice

    def __str__(self):
        return f"{self.worker.user.first_name} - {self.skill.name} (Level {self.proficiency_level})"

class ServiceZone(models.Model):
    """Geofencing for dispatching (Keep it simple first: Map by Zip Codes)"""
    workspace = models.ForeignKey(Workspace, on_delete=models.CASCADE, related_name='service_zones')
    name = models.CharField(max_length=100) # e.g., "North Broward County"
    
    # Store a list of zip codes this zone covers like: ["33301", "33302", "33304"]
    active_zip_codes = models.JSONField(default=list)

    class Meta:
        db_table = 'workspaces_servicezone'

    def __str__(self):
        return f"{self.name} Zone"


class EmployeeDocumentRequirement(models.Model):
    DOCUMENT_TYPE_CHOICES = [
        ('drivers_license', "Driver's license"),
        ('identity', 'Identity document'),
        ('certification', 'Certification / license'),
        ('tax', 'Tax form'),
        ('insurance', 'Insurance document'),
        ('other', 'Other'),
    ]

    account = models.ForeignKey(CustomerAccount, on_delete=models.CASCADE, related_name='document_requirements')
    requested_members = models.ManyToManyField(
        CustomerAccountMember,
        blank=True,
        related_name='document_requests',
    )
    title = models.CharField(max_length=150)
    document_type = models.CharField(max_length=30, choices=DOCUMENT_TYPE_CHOICES, default='other')
    instructions = models.TextField(blank=True)
    required_by_default = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'workspaces_employeedocumentrequirement'
        ordering = ('title',)


class EmployeeDocument(models.Model):
    STATUS_CHOICES = [
        ('pending', 'Pending review'),
        ('approved', 'Approved'),
        ('rejected', 'Needs replacement'),
    ]

    account = models.ForeignKey(CustomerAccount, on_delete=models.CASCADE, related_name='employee_documents')
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='employee_documents')
    requirement = models.ForeignKey(
        EmployeeDocumentRequirement,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='submissions',
    )
    document_type = models.CharField(max_length=30, choices=EmployeeDocumentRequirement.DOCUMENT_TYPE_CHOICES)
    title = models.CharField(max_length=150)
    file = models.FileField(upload_to='employee_documents/%Y/%m/')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    expiration_date = models.DateField(null=True, blank=True)
    uploaded_at = models.DateTimeField(auto_now_add=True)
    reviewed_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='reviewed_employee_documents')
    reviewed_at = models.DateTimeField(null=True, blank=True)
    review_notes = models.TextField(blank=True)

    class Meta:
        db_table = 'workspaces_employeedocument'
        ordering = ('-uploaded_at',)

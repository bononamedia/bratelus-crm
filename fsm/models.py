from django.db import models
from django.contrib.auth.models import User
from organizations.models import Workspace, WorkerProfile, Skill, ServiceZone
from crm.models.contacts import Account, Contact, Property

# ==========================================
# 1 - CORE: THE JOB ENGINE
# ==========================================
class Job(models.Model):
    """
    The central object for the Field Service Management system. 
    Represents a specific unit of work requested by a Client.
    """
    STATUS_CHOICES = [
        ('pending', 'Pending / Unassigned'),
        ('dispatched', 'Dispatched (Waiting for Accept)'),
        ('accepted', 'Accepted'),
        ('en_route', 'En Route'),
        ('in_progress', 'Clocked In / In Progress'),
        ('completed', 'Completed'),
        ('canceled', 'Canceled')
    ]

    JOB_TYPE_CHOICES = [
        ('queued', 'On-Demand / Queued'),
        ('scheduled', 'Fixed Schedule')
    ]

    FREQUENCY_CHOICES = [
        ('one_time', 'One Time'),
        ('daily', 'Daily'),
        ('weekly', 'Weekly'),
        ('bi_weekly', 'Bi-Weekly'),
        ('monthly', 'Monthly')
    ]

    COMPLETION_MODE_CHOICES = [
        ('tasks', 'Complete each task'),
        ('project', 'Complete the whole project'),
    ]
    COMPLETION_NOTIFICATION_CHOICES = [
        ('none', 'Do not notify'),
        ('email', 'Email'),
        ('sms', 'SMS'),
        ('both', 'Email and SMS'),
    ]
    
    COMMISSION_TYPE_CHOICES = [
        ('flat', 'Flat Amount ($)'),
        ('percent', 'Percentage (%)'),
    ]

    # --- Relationships ---
    organization = models.ForeignKey(Workspace, on_delete=models.CASCADE, related_name='jobs')
    account = models.ForeignKey(Account, on_delete=models.CASCADE, related_name='jobs')
    property = models.ForeignKey(Property, on_delete=models.CASCADE, null=True, blank=True)
    
    # --- Details ---
    title = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    
    # --- Scheduling & Time ---
    job_type = models.CharField(max_length=20, choices=JOB_TYPE_CHOICES, default='scheduled')
    frequency = models.CharField(max_length=20, choices=FREQUENCY_CHOICES, default='one_time')
    requested_time = models.TimeField(null=True, blank=True)
    estimated_duration_minutes = models.IntegerField(default=60)
    scheduled_start = models.DateTimeField(null=True, blank=True)
    clocked_in_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    blocked_by = models.ForeignKey('self', on_delete=models.SET_NULL, null=True, blank=True, related_name='blocks_jobs', help_text="This job cannot start until the blocked job is completed.")
    completion_mode = models.CharField(max_length=20, choices=COMPLETION_MODE_CHOICES, default='tasks')
    require_location = models.BooleanField(default=True)
    arrival_radius_meters = models.PositiveIntegerField(default=250)
    require_closeout_confirmation = models.BooleanField(default=True)
    closeout_instruction = models.CharField(max_length=255, blank=True, default='Secure the property and confirm the site is closed.')
    completion_contact = models.ForeignKey(Contact, on_delete=models.SET_NULL, null=True, blank=True, related_name='completion_notifications')
    completion_notification_method = models.CharField(max_length=10, choices=COMPLETION_NOTIFICATION_CHOICES, default='none')
    completion_message_override = models.TextField(blank=True)
    completion_notification_queued_at = models.DateTimeField(null=True, blank=True)

    # --- Finance (Client Billing) ---
    RATE_TYPE_CHOICES = [('flat', 'Flat Rate'), ('hourly', 'Hourly')]
    client_rate_type = models.CharField(max_length=10, choices=RATE_TYPE_CHOICES, default='flat')
    client_given_price = models.DecimalField(max_digits=8, decimal_places=2, default=0.00)
    additional_expense = models.DecimalField(max_digits=8, decimal_places=2, default=0.00)
    client_tip = models.DecimalField(max_digits=8, decimal_places=2, default=0.00)
    
    # FIX: Linked to actual tokenized payment methods!
    payment_method = models.ForeignKey('crm.PaymentMethod', on_delete=models.SET_NULL, null=True, blank=True, help_text="The saved card to charge for this job.")
    finance_notes = models.TextField(blank=True)
    
    # --- Sales & Commission ---
    account_manager = models.ForeignKey(WorkerProfile, on_delete=models.SET_NULL, null=True, blank=True, related_name='managed_jobs')
    commission_type = models.CharField(max_length=10, choices=COMMISSION_TYPE_CHOICES, default='flat')
    commission_amount = models.DecimalField(max_digits=8, decimal_places=2, default=0.00)

    # --- Routing & Queue Logic ---
    required_skill = models.ForeignKey(Skill, on_delete=models.SET_NULL, null=True, blank=True)
    minimum_proficiency = models.IntegerField(default=2) 
    service_zone = models.ForeignKey(ServiceZone, on_delete=models.SET_NULL, null=True, blank=True)
    
    # --- Location Data ---
    location_address = models.CharField(max_length=255, blank=True, help_text="OVERRIDE: Leave blank to use the Property address. Only use for ad-hoc locations.")
    location_lat = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    location_lng = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    
    # --- Extensibility ---
    custom_data = models.JSONField(default=dict, blank=True)

    def __str__(self):
        return f"[{self.get_job_type_display()}] {self.title}"


# ==========================================
# 2 - PAYROLL: THE WORKER ASSIGNMENT ENGINE
# ==========================================
class JobAssignment(models.Model):
    """
    Links multiple workers to a single job with custom pay rates for this specific shift.
    This solves the 'Dual-Payment' problem where workers and clients are billed differently.
    """
    PAY_TYPE_CHOICES = [('flat', 'Flat Rate'), ('hourly', 'Hourly')]

    job = models.ForeignKey(Job, on_delete=models.CASCADE, related_name='worker_assignments')
    worker = models.ForeignKey(WorkerProfile, on_delete=models.CASCADE, related_name='job_assignments')
    
    pay_type = models.CharField(max_length=10, choices=PAY_TYPE_CHOICES, default='flat')
    pay_rate = models.DecimalField(max_digits=8, decimal_places=2, default=0.00)
    tip_split = models.DecimalField(max_digits=8, decimal_places=2, default=0.00)

    is_primary_worker = models.BooleanField(default=False)
    accepted_at = models.DateTimeField(null=True, blank=True)
    arrived_at = models.DateTimeField(null=True, blank=True)
    clocked_in_at = models.DateTimeField(null=True, blank=True)
    work_completed_at = models.DateTimeField(null=True, blank=True)
    clocked_out_at = models.DateTimeField(null=True, blank=True)
    closeout_confirmed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        unique_together = ('job', 'worker')

    def __str__(self):
        return f"{self.worker.user.first_name} -> {self.job.title} (${self.pay_rate})"


# ==========================================
# 3 - FIELD EXECUTION: TASKS & CHECKLISTS
# ==========================================
class JobTask(models.Model):
    """
    The specific checklist items the worker must complete before finishing the job.
    """
    job = models.ForeignKey(Job, on_delete=models.CASCADE, related_name='tasks')
    description = models.CharField(max_length=255)
    requires_evidence = models.BooleanField(default=False)
    is_completed = models.BooleanField(default=False)
    completion_photo = models.ImageField(upload_to='job_photos/', null=True, blank=True)
    completion_notes = models.TextField(blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    completed_by = models.ForeignKey(WorkerProfile, on_delete=models.SET_NULL, null=True, blank=True, related_name='completed_job_tasks')

    def __str__(self):
        return f"Task for Job #{self.job.id}: {self.description}"


# ==========================================
# 4 - TRACKING: LIVE GPS INGESTION
# ==========================================
class WorkerLocation(models.Model):
    """
    Stores the historical GPS breadcrumb trails flushed from the Redis cache.
    """
    worker = models.ForeignKey(WorkerProfile, on_delete=models.CASCADE)
    job = models.ForeignKey(Job, on_delete=models.CASCADE, null=True, blank=True)
    lat = models.DecimalField(max_digits=9, decimal_places=6)
    lng = models.DecimalField(max_digits=9, decimal_places=6)
    timestamp = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.worker.user.username} Location at {self.timestamp}"


# ==========================================
# 5 - QUALITY CONTROL: PHOTO VERIFICATION
# ==========================================
class JobEvidence(models.Model):
    """
    Stores photo proof uploaded by the mobile app when completing a task.
    Includes metadata for automated background EXIF/GPS verification against the Property location.
    """
    job = models.ForeignKey(Job, on_delete=models.CASCADE, related_name='evidence')
    task = models.ForeignKey(JobTask, on_delete=models.CASCADE, related_name='evidence', null=True, blank=True)
    
    # Image stored in the Cloudflare R2 Bucket
    photo = models.FileField(upload_to='evidence/%Y/%m/%d/')
    media_type = models.CharField(max_length=10, choices=[('photo', 'Photo'), ('video', 'Video')], default='photo')
    uploaded_by = models.ForeignKey(WorkerProfile, on_delete=models.SET_NULL, null=True, blank=True, related_name='job_evidence')
    note = models.TextField(blank=True)
    
    # Metadata for verification
    captured_at = models.DateTimeField()
    lat = models.DecimalField(max_digits=9, decimal_places=6)
    lng = models.DecimalField(max_digits=9, decimal_places=6)
    
    # Automated QC Engine Results
    is_verified = models.BooleanField(default=False)
    qc_notes = models.TextField(blank=True)

    def __str__(self):
        task_label = f"Task #{self.task_id}" if self.task_id else "Project"
        return f"Evidence for Job #{self.job.id} - {task_label}"


class FieldShift(models.Model):
    worker = models.ForeignKey(WorkerProfile, on_delete=models.CASCADE, related_name='field_shifts')
    workspace = models.ForeignKey(Workspace, on_delete=models.CASCADE, related_name='field_shifts')
    started_at = models.DateTimeField(auto_now_add=True)
    ended_at = models.DateTimeField(null=True, blank=True)
    start_lat = models.DecimalField(max_digits=9, decimal_places=6)
    start_lng = models.DecimalField(max_digits=9, decimal_places=6)
    end_lat = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    end_lng = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)

    class Meta:
        ordering = ('-started_at',)

    @property
    def is_active(self):
        return self.ended_at is None


class FieldEvent(models.Model):
    EVENT_CHOICES = [
        ('shift_started', 'Available for work'),
        ('shift_ended', 'Shift ended'),
        ('job_accepted', 'Job accepted'),
        ('arrived', 'Arrived at location'),
        ('work_started', 'Work started'),
        ('task_completed', 'Task completed'),
        ('note_added', 'Note added'),
        ('evidence_added', 'Evidence added'),
        ('closeout_confirmed', 'Closeout confirmed'),
        ('job_completed', 'Job completed'),
    ]
    TRANSLATION_STATUS_CHOICES = [
        ('not_needed', 'Not needed'),
        ('pending', 'Pending'),
        ('translated', 'Translated'),
        ('failed', 'Failed'),
    ]

    workspace = models.ForeignKey(Workspace, on_delete=models.CASCADE, related_name='field_events')
    worker = models.ForeignKey(WorkerProfile, on_delete=models.CASCADE, related_name='field_events')
    job = models.ForeignKey(Job, on_delete=models.CASCADE, related_name='field_events', null=True, blank=True)
    task = models.ForeignKey(JobTask, on_delete=models.SET_NULL, related_name='field_events', null=True, blank=True)
    event_type = models.CharField(max_length=30, choices=EVENT_CHOICES)
    occurred_at = models.DateTimeField(auto_now_add=True)
    lat = models.DecimalField(max_digits=9, decimal_places=6)
    lng = models.DecimalField(max_digits=9, decimal_places=6)
    accuracy = models.DecimalField(max_digits=8, decimal_places=2, default=0)
    note_original = models.TextField(blank=True)
    note_english = models.TextField(blank=True)
    source_language = models.CharField(max_length=10, blank=True)
    translation_status = models.CharField(max_length=20, choices=TRANSLATION_STATUS_CHOICES, default='not_needed')

    class Meta:
        ordering = ('-occurred_at',)


class CompletionNotificationSetting(models.Model):
    DEFAULT_MESSAGE = (
        'Dear {{first_name}},\n\n'
        'Thank you for trusting us with {{service}}. Please check everything and let us know '
        'whether we exceeded your expectations. You may always reply to us.\n\n'
        'Sincerely,\n{{workspace_name}}'
    )

    workspace = models.OneToOneField(Workspace, on_delete=models.CASCADE, related_name='completion_notification_setting')
    email_subject = models.CharField(max_length=200, default='Your {{service}} is complete')
    message_template = models.TextField(default=DEFAULT_MESSAGE)
    reply_to_email = models.EmailField(blank=True)
    sms_from_number = models.CharField(max_length=30, blank=True)
    updated_at = models.DateTimeField(auto_now=True)


class CompletionNotificationDelivery(models.Model):
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('sent', 'Sent'),
        ('failed', 'Failed'),
    ]
    job = models.ForeignKey(Job, on_delete=models.CASCADE, related_name='completion_notification_deliveries')
    contact = models.ForeignKey(Contact, on_delete=models.SET_NULL, null=True, blank=True)
    channel = models.CharField(max_length=10, choices=[('email', 'Email'), ('sms', 'SMS')])
    recipient = models.CharField(max_length=255, blank=True)
    subject = models.CharField(max_length=255, blank=True)
    message = models.TextField()
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    provider_reference = models.CharField(max_length=255, blank=True)
    error_message = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    sent_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ('-created_at',)
        constraints = [
            models.UniqueConstraint(fields=('job', 'channel'), name='fsm_unique_completion_delivery_channel'),
        ]

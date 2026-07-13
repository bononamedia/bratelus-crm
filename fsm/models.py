from django.db import models
from django.contrib.auth.models import User
from organizations.models import Workspace, WorkerProfile, Skill, ServiceZone
from crm.models.contacts import Account, Property

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
    clocked_in_at = models.DateTimeField(null=True, blank=True)
    clocked_out_at = models.DateTimeField(null=True, blank=True)

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
    is_completed = models.BooleanField(default=False)
    completion_photo = models.ImageField(upload_to='job_photos/', null=True, blank=True)

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
    task = models.ForeignKey(JobTask, on_delete=models.CASCADE, related_name='evidence')
    
    # Image stored in the Cloudflare R2 Bucket
    photo = models.ImageField(upload_to='evidence/%Y/%m/%d/')
    
    # Metadata for verification
    captured_at = models.DateTimeField()
    lat = models.DecimalField(max_digits=9, decimal_places=6)
    lng = models.DecimalField(max_digits=9, decimal_places=6)
    
    # Automated QC Engine Results
    is_verified = models.BooleanField(default=False)
    qc_notes = models.TextField(blank=True)

    def __str__(self):
        return f"Evidence for Job #{self.job.id} - Task #{self.task.id}"
from django.contrib import admin
from .models import Job, JobTask, WorkerLocation, JobAssignment, JobEvidence, MaterialRun, WorkActivity

class JobAssignmentInline(admin.TabularInline):
    model = JobAssignment
    extra = 1

@admin.register(Job)
class JobAdmin(admin.ModelAdmin):
    list_display = ('title', 'organization', 'account', 'status', 'job_type', 'scheduled_start')
    list_filter = ('status', 'job_type', 'frequency', 'organization')
    search_fields = ('title', 'description', 'location_address', 'account__name')
    
    inlines = [JobAssignmentInline] 
    
    fieldsets = (
        ('Core Details', {
            'fields': ('organization', 'account', 'property', 'title', 'description', 'status')
        }),
        ('Scheduling Section', {
            'fields': ('job_type', 'frequency', 'requested_time', 'estimated_duration_minutes', 'scheduled_start', 'clocked_in_at', 'completed_at', 'blocked_by')
        }),
        ('Finance Section (Client)', {
            # FIX: Swapped payment_type for payment_method
            'fields': ('client_rate_type', 'client_given_price', 'additional_expense', 'client_tip', 'payment_method', 'finance_notes')
        }),
        ('Sales Section', {
            # FIX: Added commission_type
            'fields': ('account_manager', 'commission_type', 'commission_amount')
        }),
        # FIX: Quality Control Section completely removed!
        ('Routing & Location', {
            'fields': ('required_skill', 'minimum_proficiency', 'service_zone', 'location_address', 'location_lat', 'location_lng')
        }),
        ('Advanced', {
            'classes': ('collapse',),
            'fields': ('custom_data',)
        }),
    )

# Register the other models here. 
@admin.register(JobTask)
class JobTaskAdmin(admin.ModelAdmin):
    list_display = ('description', 'job', 'assigned_worker', 'requires_evidence', 'is_completed')
    list_filter = ('requires_evidence', 'is_completed', 'job__organization')
    search_fields = ('description', 'job__title', 'assigned_worker__user__username')

admin.site.register(WorkerLocation)
admin.site.register(JobEvidence) # Added your new Evidence model
admin.site.register(MaterialRun)
admin.site.register(WorkActivity)

from django.contrib import admin
from .models import (
    CustomerAccount, CustomerAccountMember,
    Workspace, WorkspaceMember, WorkerProfile, CustomField, 
    FormLayout, DashboardWidget, Skill, WorkerSkill, ServiceZone,
    WorkspaceEmailDomain, WorkspaceEmailConnection,
    EmployeeDocument, EmployeeDocumentRequirement,
)

admin.site.site_header = 'Bratelus Superadmin'
admin.site.site_title = 'Bratelus Admin'
admin.site.index_title = 'Operations Control'
admin.site.has_permission = lambda request: request.user.is_active and request.user.is_superuser


class WorkspaceMemberInline(admin.TabularInline):
    model = WorkspaceMember
    extra = 1


class CustomerAccountMemberInline(admin.TabularInline):
    model = CustomerAccountMember
    extra = 0


@admin.register(CustomerAccount)
class CustomerAccountAdmin(admin.ModelAdmin):
    list_display = ('name', 'owner', 'created_at')
    search_fields = ('name', 'owner__email', 'owner__username')
    autocomplete_fields = ('owner',)
    inlines = [CustomerAccountMemberInline]


@admin.register(CustomerAccountMember)
class CustomerAccountMemberAdmin(admin.ModelAdmin):
    list_display = ('user', 'account', 'role', 'can_work_jobs', 'photo_required', 'drivers_license_required', 'is_active')
    list_filter = ('account', 'role', 'can_work_jobs', 'photo_required', 'drivers_license_required', 'is_active')
    search_fields = ('user__email', 'user__username', 'account__name')

@admin.register(Workspace)
class WorkspaceAdmin(admin.ModelAdmin):
    list_display = ('name', 'slug', 'created_by', 'created_at')
    prepopulated_fields = {'slug': ('name',)}
    search_fields = ('name', 'slug')
    ordering = ('name',)
    inlines = [WorkspaceMemberInline]

@admin.register(WorkspaceMember)
class WorkspaceMemberAdmin(admin.ModelAdmin):
    list_display = ('user', 'workspace', 'role', 'can_view_billing', 'is_active')
    list_filter = ('workspace', 'role', 'can_view_billing', 'is_active')
    search_fields = ('user__username', 'user__email', 'workspace__name')
    autocomplete_fields = ('user', 'workspace')


@admin.register(WorkspaceEmailDomain)
class WorkspaceEmailDomainAdmin(admin.ModelAdmin):
    list_display = ('domain', 'workspace', 'is_verified', 'created_at')
    list_filter = ('workspace', 'is_verified')
    search_fields = ('domain', 'workspace__name')
    autocomplete_fields = ('workspace',)


@admin.register(WorkspaceEmailConnection)
class WorkspaceEmailConnectionAdmin(admin.ModelAdmin):
    list_display = ('from_email', 'display_name', 'workspace', 'connection_type', 'status')
    list_filter = ('workspace', 'connection_type', 'status')
    search_fields = ('from_email', 'display_name', 'workspace__name', 'domain__domain')
    autocomplete_fields = ('workspace', 'domain', 'created_by')

@admin.register(WorkerProfile)
class WorkerProfileAdmin(admin.ModelAdmin):
    list_display = ('user', 'phone', 'is_admin')
    list_filter = ('is_admin', 'workspaces')
    search_fields = ('user__username', 'user__email', 'user__first_name', 'user__last_name', 'phone')
    autocomplete_fields = ('user',)
    filter_horizontal = ('workspaces',)


@admin.register(CustomField)
class CustomFieldAdmin(admin.ModelAdmin):
    list_display = ('label', 'internal_name', 'target_model', 'field_type', 'workspace', 'is_required')
    list_filter = ('workspace', 'target_model', 'field_type', 'is_required')
    search_fields = ('label', 'internal_name', 'workspace__name')
    autocomplete_fields = ('workspace',)
    ordering = ('workspace__name', 'target_model', 'label')


@admin.register(FormLayout)
class FormLayoutAdmin(admin.ModelAdmin):
    list_display = ('workspace', 'target_model')
    list_filter = ('workspace', 'target_model')
    search_fields = ('workspace__name', 'target_model')
    autocomplete_fields = ('workspace',)


@admin.register(DashboardWidget)
class DashboardWidgetAdmin(admin.ModelAdmin):
    list_display = ('user', 'widget_type', 'width', 'height', 'x_position', 'y_position')
    list_filter = ('widget_type',)
    search_fields = ('user__username', 'widget_type')
    autocomplete_fields = ('user',)


@admin.register(Skill)
class SkillAdmin(admin.ModelAdmin):
    list_display = ('name', 'customer_account', 'workspace', 'description')
    list_filter = ('customer_account', 'workspace')
    search_fields = ('name', 'description', 'customer_account__name', 'workspace__name')
    autocomplete_fields = ('customer_account', 'workspace')
    ordering = ('customer_account__name', 'name')


@admin.register(WorkerSkill)
class WorkerSkillAdmin(admin.ModelAdmin):
    list_display = ('worker', 'skill', 'proficiency_level')
    list_filter = ('skill__workspace', 'skill', 'proficiency_level')
    search_fields = ('worker__user__username', 'worker__user__first_name', 'worker__user__last_name', 'skill__name')
    autocomplete_fields = ('worker', 'skill')


@admin.register(EmployeeDocumentRequirement)
class EmployeeDocumentRequirementAdmin(admin.ModelAdmin):
    list_display = ('title', 'account', 'document_type', 'required_by_default', 'is_active')
    list_filter = ('account', 'document_type', 'required_by_default', 'is_active')
    search_fields = ('title', 'account__name')
    filter_horizontal = ('requested_members',)


@admin.register(EmployeeDocument)
class EmployeeDocumentAdmin(admin.ModelAdmin):
    list_display = ('title', 'user', 'account', 'document_type', 'status', 'uploaded_at')
    list_filter = ('account', 'document_type', 'status')
    search_fields = ('title', 'user__email', 'user__username', 'account__name')
    readonly_fields = ('uploaded_at', 'reviewed_at')


@admin.register(ServiceZone)
class ServiceZoneAdmin(admin.ModelAdmin):
    list_display = ('name', 'workspace')
    list_filter = ('workspace',)
    search_fields = ('name', 'workspace__name')
    autocomplete_fields = ('workspace',)
    ordering = ('workspace__name', 'name')

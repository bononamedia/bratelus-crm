from django import forms
from django.contrib import admin, messages
from django.core.mail import EmailMultiAlternatives
from .models import (
    CustomerAccount, CustomerAccountMember,
    Workspace, WorkspaceMember, WorkerProfile, CustomField, 
    FormLayout, DashboardWidget, Skill, WorkerSkill, ServiceZone,
    WorkspaceEmailDomain, WorkspaceEmailConnection,
    EmployeeDocument, EmployeeDocumentRequirement,
    UserEmailVerification,
    PlatformEmailSettings,
)
from .emailing import platform_email_delivery

admin.site.site_header = 'Bratelus Superadmin'
admin.site.site_title = 'Bratelus Admin'
admin.site.index_title = 'Operations Control'
admin.site.has_permission = lambda request: request.user.is_active and request.user.is_superuser


@admin.register(UserEmailVerification)
class UserEmailVerificationAdmin(admin.ModelAdmin):
    list_display = ('user', 'sent_at', 'verified_at')
    search_fields = ('user__email', 'user__username')


class PlatformEmailSettingsForm(forms.ModelForm):
    smtp_password = forms.CharField(
        label='SMTP password',
        required=False,
        widget=forms.PasswordInput(render_value=False),
        help_text='Enter a new password to replace the saved credential. Leave blank to keep it unchanged.',
    )

    class Meta:
        model = PlatformEmailSettings
        exclude = ('smtp_password_encrypted',)

    def clean(self):
        cleaned = super().clean()
        if cleaned.get('is_active') and not cleaned.get('smtp_password') and not self.instance.password_configured:
            self.add_error('smtp_password', 'A password is required while platform email is active.')
        return cleaned

    def save(self, commit=True):
        instance = super().save(commit=False)
        password = self.cleaned_data.get('smtp_password')
        if password:
            instance.set_smtp_password(password)
        if commit:
            instance.save()
        return instance


@admin.register(PlatformEmailSettings)
class PlatformEmailSettingsAdmin(admin.ModelAdmin):
    form = PlatformEmailSettingsForm
    list_display = ('from_email', 'smtp_host', 'smtp_port', 'is_active', 'password_configured', 'updated_at')
    readonly_fields = ('password_configured', 'updated_at')
    actions = ('send_test_email',)
    fieldsets = (
        ('Sender', {'fields': ('display_name', 'from_email', 'support_email', 'is_active')}),
        ('SMTP server', {'fields': ('smtp_host', 'smtp_port', 'smtp_username', 'smtp_password', 'password_configured')}),
        ('Security', {'fields': ('use_tls', 'use_ssl')}),
        ('Status', {'fields': ('updated_at',)}),
    )

    def has_add_permission(self, request):
        return not PlatformEmailSettings.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False

    @admin.action(description='Send a test message to the support address')
    def send_test_email(self, request, queryset):
        config = queryset.first()
        if not config:
            self.message_user(request, 'Select the platform email settings record.', level=messages.ERROR)
            return
        if not config.is_active:
            self.message_user(request, 'Activate platform email before sending a test.', level=messages.ERROR)
            return
        try:
            connection, from_email, support_email = platform_email_delivery()
            message = EmailMultiAlternatives(
                'Bratelus platform email test',
                'Your Bratelus platform SMTP configuration is working.',
                from_email,
                [support_email],
                connection=connection,
            )
            message.attach_alternative(
                '<div style="font-family:Arial,sans-serif;padding:24px"><h1 style="color:#1d4ed8">Bratelus email is ready.</h1><p>Your platform SMTP configuration is working.</p></div>',
                'text/html',
            )
            message.send(fail_silently=False)
        except Exception as exc:
            self.message_user(request, f'Test email failed: {exc}', level=messages.ERROR)
            return
        self.message_user(request, f'Test email sent to {support_email}.', level=messages.SUCCESS)


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

from django.contrib import admin
from .models.contacts import Account, Contact, Property, PaymentMethod
from .models.notes import CRMNote

@admin.register(Account)
class AccountAdmin(admin.ModelAdmin):
    list_display = ('name', 'organization', 'phone', 'archived_at')
    list_filter = ('organization', 'archived_at')
    search_fields = ('name', 'phone', 'billing_address', 'organization__name')
    autocomplete_fields = ('organization',)

@admin.register(Contact)
class ContactAdmin(admin.ModelAdmin):
    list_display = ('first_name', 'last_name', 'email', 'organization', 'account', 'status', 'archived_at')
    list_filter = ('organization', 'status', 'external_source', 'email_opt_out', 'sms_opt_out', 'archived_at')
    search_fields = ('first_name', 'last_name', 'email', 'phone', 'mobile', 'account__name', 'external_id')
    autocomplete_fields = ('organization', 'account')

@admin.register(Property)
class PropertyAdmin(admin.ModelAdmin):
    list_display = ('name', 'address', 'account')
    search_fields = ('name', 'address', 'unit_number', 'account__name')
    autocomplete_fields = ('account',)

@admin.register(PaymentMethod)
class PaymentMethodAdmin(admin.ModelAdmin):
    list_display = ('card_type', 'last_four', 'account', 'is_default')
    list_filter = ('is_default', 'card_type')
    search_fields = ('card_type', 'last_four', 'account__name')
    autocomplete_fields = ('account', 'assigned_property')


@admin.register(CRMNote)
class CRMNoteAdmin(admin.ModelAdmin):
    list_display = ('target_type', 'target_summary', 'category', 'visibility', 'workspace', 'author', 'created_at')
    list_filter = ('workspace', 'target_type', 'category', 'visibility', 'created_at')
    search_fields = (
        'body', 'account__name', 'contact__first_name', 'contact__last_name',
        'property__name', 'job__title', 'author__username',
    )
    autocomplete_fields = ('workspace', 'author', 'account', 'contact', 'property', 'job')
    readonly_fields = ('created_at', 'updated_at')

    @admin.display(description='Target')
    def target_summary(self, obj):
        return obj.target_object

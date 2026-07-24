from django.contrib import admin
from .models import (
    AccountingConnection,
    BillingEvent,
    CreditNote,
    Estimate,
    EstimateLineItem,
    Invoice,
    LineItem,
    PaymentReceived,
    PlatformInvoice,
    RecurringInvoice,
    SeatPricingTier,
    SubscriptionPlan,
    WorkspacePaymentOption,
    WorkspaceSubscription,
)


class LineItemInline(admin.TabularInline):
    model = LineItem
    extra = 1


class EstimateLineItemInline(admin.TabularInline):
    model = EstimateLineItem
    extra = 1


@admin.register(Estimate)
class EstimateAdmin(admin.ModelAdmin):
    list_display = ('estimate_number', 'account', 'organization', 'status', 'issue_date', 'total_amount')
    list_filter = ('organization', 'status')
    search_fields = ('estimate_number', 'account__name')
    inlines = (EstimateLineItemInline,)


@admin.register(Invoice)
class InvoiceAdmin(admin.ModelAdmin):
    list_display = ('invoice_number', 'account', 'organization', 'status', 'due_date', 'total_amount')
    list_filter = ('organization', 'status', 'due_date')
    search_fields = ('invoice_number', 'account__name', 'organization__name')
    autocomplete_fields = ('organization', 'account')
    inlines = [LineItemInline]


@admin.register(LineItem)
class LineItemAdmin(admin.ModelAdmin):
    list_display = ('description', 'invoice', 'quantity', 'unit_price', 'total_price')
    search_fields = ('description', 'invoice__invoice_number')
    autocomplete_fields = ('invoice', 'job')


@admin.register(PaymentReceived)
class PaymentReceivedAdmin(admin.ModelAdmin):
    list_display = ('payment_number', 'account', 'job', 'invoice', 'method', 'amount', 'payment_date')
    list_filter = ('organization', 'method', 'payment_date')
    search_fields = ('payment_number', 'account__name', 'invoice__invoice_number', 'job__title', 'reference')
    autocomplete_fields = ('organization', 'account', 'invoice', 'job')


class SeatPricingTierInline(admin.TabularInline):
    model = SeatPricingTier
    extra = 0


@admin.register(SubscriptionPlan)
class SubscriptionPlanAdmin(admin.ModelAdmin):
    list_display = ('name', 'base_monthly_amount', 'included_users', 'currency', 'is_active')
    list_filter = ('is_active', 'currency')
    search_fields = ('name', 'code')
    prepopulated_fields = {'code': ('name',)}
    inlines = (SeatPricingTierInline,)


@admin.register(WorkspaceSubscription)
class WorkspaceSubscriptionAdmin(admin.ModelAdmin):
    list_display = ('workspace', 'plan', 'status', 'seat_count', 'billing_email')
    list_filter = ('status', 'plan')
    search_fields = ('workspace__name', 'billing_email', 'stripe_customer_id', 'stripe_subscription_id')
    autocomplete_fields = ('workspace', 'plan')


@admin.register(PlatformInvoice)
class PlatformInvoiceAdmin(admin.ModelAdmin):
    list_display = ('invoice_number', 'workspace', 'status', 'amount_due', 'amount_paid', 'created_at')
    list_filter = ('status', 'currency')
    search_fields = ('invoice_number', 'workspace__name', 'stripe_invoice_id')


@admin.register(BillingEvent)
class BillingEventAdmin(admin.ModelAdmin):
    list_display = ('event_type', 'workspace', 'summary', 'created_at')
    list_filter = ('event_type',)
    search_fields = ('summary', 'stripe_event_id', 'workspace__name')
    readonly_fields = ('created_at',)


admin.site.register(RecurringInvoice)
admin.site.register(CreditNote)
admin.site.register(WorkspacePaymentOption)
admin.site.register(AccountingConnection)

from django.contrib import admin
from .models import Invoice, LineItem


class LineItemInline(admin.TabularInline):
    model = LineItem
    extra = 1


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

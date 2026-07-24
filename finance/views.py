from decimal import Decimal, InvalidOperation

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.db.models import Sum
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.dateparse import parse_date

from crm.models.contacts import Account, Contact, PaymentMethod, Property
from finance.models import (
    AccountingConnection,
    CreditNote,
    Estimate,
    EstimateLineItem,
    Invoice,
    LineItem,
    PaymentReceived,
    RecurringInvoice,
    WorkspacePaymentOption,
)
from fsm.models import Job, JobAssignment, MaterialRun
from organizations.permissions import user_can_manage_workspace, worker_profile_for_workspace
from workforce.services import assignment_time_and_earnings


PAYMENT_METHODS = [
    ('card', 'Credit / debit card', 'Card checkout using the connected processor'),
    ('stripe', 'Stripe', 'Online card and bank payments'),
    ('paypal', 'PayPal', 'PayPal checkout and wallet payments'),
    ('paysimple', 'PaySimple', 'ACH and card processing'),
    ('zelle', 'Zelle', 'Manual transfer instructions'),
    ('pix', 'PIX', 'Brazilian instant payment instructions'),
    ('check', 'Check', 'Check payable and mailing instructions'),
    ('cash', 'Cash', 'Record cash collected offline'),
    ('bank_transfer', 'Bank transfer', 'ACH or wire transfer instructions'),
]


def _finance_workspace(request):
    workspace = getattr(request, 'active_organization', None)
    if not user_can_manage_workspace(request.user, workspace):
        if worker_profile_for_workspace(request.user, workspace):
            return None
        raise PermissionDenied('Only workspace admins can access Finance.')
    return workspace


def _money(value, default='0'):
    try:
        return Decimal(str(value or default)).quantize(Decimal('0.01'))
    except (InvalidOperation, TypeError, ValueError):
        return Decimal(default).quantize(Decimal('0.01'))


def _next_number(model, workspace, prefix):
    latest_id = model.objects.order_by('-id').values_list('id', flat=True).first() or 0
    return f'{prefix}-{workspace.id}-{latest_id + 1:05d}'


def _workspace_sales_context(workspace):
    accounts = Account.objects.filter(organization=workspace, archived_at__isnull=True).order_by('name')
    return {
        'accounts': accounts,
        'contacts': Contact.objects.filter(organization=workspace, archived_at__isnull=True).order_by('first_name', 'last_name'),
        'properties': Property.objects.filter(account__organization=workspace).select_related('account').order_by('name'),
        'jobs': Job.objects.filter(organization=workspace).exclude(status='canceled').select_related('account').order_by('-scheduled_start', '-id'),
        'estimates': Estimate.objects.filter(organization=workspace).select_related('account', 'converted_invoice')[:100],
        'invoices': Invoice.objects.filter(organization=workspace).select_related('account', 'job').order_by('-issue_date', '-id')[:100],
        'recurring_invoices': RecurringInvoice.objects.filter(organization=workspace).select_related('account')[:100],
        'payments_received': PaymentReceived.objects.filter(organization=workspace).select_related('account', 'invoice', 'job')[:100],
        'credit_notes': CreditNote.objects.filter(organization=workspace).select_related('account', 'invoice')[:100],
    }


@login_required
def finance_overview_view(request):
    active_org = _finance_workspace(request)
    if active_org is None:
        return redirect('employee_profile')

    invoices = Invoice.objects.filter(organization=active_org).select_related('account')
    payment_methods = PaymentMethod.objects.filter(account__organization=active_org)
    payments = PaymentReceived.objects.filter(organization=active_org)
    estimates = Estimate.objects.filter(organization=active_org)
    open_invoices = invoices.exclude(status__in=['paid', 'canceled'])
    open_balance = sum((invoice.balance_due for invoice in open_invoices), Decimal('0'))

    context = {
        'invoices': invoices.order_by('-issue_date', '-id')[:8],
        'estimates': estimates.select_related('account')[:6],
        'finance_stats': {
            'estimate_count': estimates.count(),
            'invoice_count': invoices.count(),
            'open_invoice_count': open_invoices.count(),
            'payment_method_count': payment_methods.count(),
            'payments_received': payments.aggregate(total=Sum('amount')).get('total') or 0,
            'total_billed': invoices.aggregate(total=Sum('total_amount')).get('total') or 0,
            'open_balance': open_balance,
        },
    }
    return render(request, 'finance_overview.html', context)


@login_required
def finance_sales_view(request):
    workspace = _finance_workspace(request)
    if workspace is None:
        return redirect('employee_profile')

    if request.method == 'POST':
        action = request.POST.get('action', '')
        account = get_object_or_404(
            Account,
            id=request.POST.get('account_id'),
            organization=workspace,
            archived_at__isnull=True,
        )
        job = Job.objects.filter(id=request.POST.get('job_id'), organization=workspace, account=account).first()
        contact = Contact.objects.filter(id=request.POST.get('contact_id'), organization=workspace, account=account).first()
        property_record = Property.objects.filter(id=request.POST.get('property_id'), account=account).first()
        quantity = _money(request.POST.get('quantity'), '1')
        unit_price = _money(request.POST.get('unit_price'))
        tax_amount = _money(request.POST.get('tax_amount'))
        subtotal = quantity * unit_price
        total = subtotal + tax_amount
        description = request.POST.get('description', '').strip() or 'Service'

        with transaction.atomic():
            if action == 'create_estimate':
                estimate = Estimate.objects.create(
                    organization=workspace,
                    account=account,
                    contact=contact,
                    property=property_record,
                    job=job,
                    estimate_number=_next_number(Estimate, workspace, 'EST'),
                    issue_date=parse_date(request.POST.get('issue_date', '')) or timezone.localdate(),
                    expiration_date=parse_date(request.POST.get('expiration_date', '')),
                    subtotal=subtotal,
                    tax_amount=tax_amount,
                    total_amount=total,
                    notes=request.POST.get('notes', '').strip(),
                    terms=request.POST.get('terms', '').strip(),
                )
                EstimateLineItem.objects.create(
                    estimate=estimate,
                    job=job,
                    description=description,
                    quantity=quantity,
                    unit_price=unit_price,
                )
                messages.success(request, f'Estimate {estimate.estimate_number} created.')
            elif action == 'create_invoice':
                due_date = parse_date(request.POST.get('due_date', '')) or timezone.localdate()
                invoice = Invoice.objects.create(
                    organization=workspace,
                    account=account,
                    contact=contact,
                    property=property_record,
                    job=job,
                    invoice_number=_next_number(Invoice, workspace, 'INV'),
                    due_date=due_date,
                    subtotal=subtotal,
                    tax_amount=tax_amount,
                    total_amount=total,
                    notes=request.POST.get('notes', '').strip(),
                    terms=request.POST.get('terms', '').strip(),
                )
                LineItem.objects.create(
                    invoice=invoice,
                    job=job,
                    description=description,
                    quantity=quantity,
                    unit_price=unit_price,
                    total_price=subtotal,
                )
                messages.success(request, f'Invoice {invoice.invoice_number} created.')
                return redirect('finance_invoice_detail', invoice_id=invoice.id)
            elif action == 'create_recurring':
                RecurringInvoice.objects.create(
                    organization=workspace,
                    account=account,
                    contact=contact,
                    property=property_record,
                    job=job,
                    name=request.POST.get('name', '').strip() or f'{account.name} recurring service',
                    frequency=request.POST.get('frequency', 'monthly'),
                    next_issue_date=parse_date(request.POST.get('next_issue_date', '')) or timezone.localdate(),
                    due_days=max(int(request.POST.get('due_days') or 30), 0),
                    line_items=[{
                        'description': description,
                        'quantity': str(quantity),
                        'unit_price': str(unit_price),
                        'job_id': job.id if job else None,
                    }],
                    subtotal=subtotal,
                    tax_amount=tax_amount,
                    total_amount=total,
                    notes=request.POST.get('notes', '').strip(),
                )
                messages.success(request, 'Recurring invoice schedule created.')
            elif action == 'record_payment':
                invoice = Invoice.objects.filter(
                    id=request.POST.get('invoice_id'),
                    organization=workspace,
                    account=account,
                ).first()
                amount = _money(request.POST.get('amount'))
                payment = PaymentReceived.objects.create(
                    organization=workspace,
                    account=account,
                    invoice=invoice,
                    job=invoice.job if invoice and invoice.job_id else job,
                    payment_number=_next_number(PaymentReceived, workspace, 'PAY'),
                    payment_date=parse_date(request.POST.get('payment_date', '')) or timezone.localdate(),
                    amount=amount,
                    method=request.POST.get('method', 'other'),
                    reference=request.POST.get('reference', '').strip(),
                    notes=request.POST.get('notes', '').strip(),
                )
                if invoice:
                    invoice.amount_paid = min(invoice.total_amount, invoice.amount_paid + amount)
                    if invoice.amount_paid >= invoice.total_amount:
                        invoice.status = 'paid'
                        invoice.paid_at = timezone.now()
                    invoice.save(update_fields=['amount_paid', 'status', 'paid_at', 'updated_at'])
                messages.success(request, f'Payment {payment.payment_number} recorded.')
            elif action == 'create_credit':
                invoice = Invoice.objects.filter(
                    id=request.POST.get('invoice_id'),
                    organization=workspace,
                    account=account,
                ).first()
                credit = CreditNote.objects.create(
                    organization=workspace,
                    account=account,
                    invoice=invoice,
                    credit_number=_next_number(CreditNote, workspace, 'CR'),
                    issue_date=parse_date(request.POST.get('issue_date', '')) or timezone.localdate(),
                    amount=_money(request.POST.get('amount')),
                    reason=request.POST.get('reason', '').strip(),
                )
                messages.success(request, f'Credit note {credit.credit_number} created.')
        return redirect(f"{request.path}?tab={request.POST.get('return_tab', 'invoices')}")

    context = _workspace_sales_context(workspace)
    context['active_tab'] = request.GET.get('tab', 'invoices')
    context['payment_methods'] = PaymentReceived.METHOD_CHOICES
    return render(request, 'finance_sales.html', context)


@login_required
@transaction.atomic
def estimate_convert_view(request, estimate_id):
    workspace = _finance_workspace(request)
    if request.method != 'POST':
        raise PermissionDenied('Estimate conversion requires confirmation.')
    estimate = get_object_or_404(
        Estimate.objects.prefetch_related('line_items'),
        id=estimate_id,
        organization=workspace,
    )
    if estimate.converted_invoice_id:
        return redirect('finance_invoice_detail', invoice_id=estimate.converted_invoice_id)
    invoice = Invoice.objects.create(
        organization=workspace,
        account=estimate.account,
        contact=estimate.contact,
        property=estimate.property,
        job=estimate.job,
        invoice_number=_next_number(Invoice, workspace, 'INV'),
        due_date=timezone.localdate(),
        subtotal=estimate.subtotal,
        tax_amount=estimate.tax_amount,
        total_amount=estimate.total_amount,
        notes=estimate.notes,
        terms=estimate.terms,
    )
    for item in estimate.line_items.all():
        LineItem.objects.create(
            invoice=invoice,
            job=item.job,
            description=item.description,
            quantity=item.quantity,
            unit_price=item.unit_price,
            total_price=item.total_price,
        )
    estimate.converted_invoice = invoice
    estimate.status = 'converted'
    estimate.save(update_fields=['converted_invoice', 'status', 'updated_at'])
    messages.success(request, f'Estimate converted to {invoice.invoice_number}.')
    return redirect('finance_invoice_detail', invoice_id=invoice.id)


@login_required
def finance_invoice_detail_view(request, invoice_id):
    workspace = _finance_workspace(request)
    invoice = get_object_or_404(
        Invoice.objects.select_related('organization', 'account', 'contact', 'property', 'job').prefetch_related('line_items', 'payments'),
        id=invoice_id,
        organization=workspace,
    )
    return render(request, 'finance_invoice_detail.html', {'invoice': invoice})


@login_required
def finance_payment_settings_view(request):
    workspace = _finance_workspace(request)
    if workspace is None:
        return redirect('employee_profile')

    if request.method == 'POST':
        method = request.POST.get('method', '')
        allowed = {item[0] for item in PAYMENT_METHODS}
        if method not in allowed:
            raise PermissionDenied('Unknown payment method.')
        option, _ = WorkspacePaymentOption.objects.get_or_create(workspace=workspace, method=method)
        option.display_name = request.POST.get('display_name', '').strip()
        option.instructions = request.POST.get('instructions', '').strip()
        option.is_enabled = request.POST.get('is_enabled') == 'yes'
        option.public_config = {
            'account_label': request.POST.get('account_label', '').strip(),
        }
        option.save()
        messages.success(request, f'{option.get_method_display()} payment settings updated.')
        return redirect('finance_payment_settings')

    existing = {option.method: option for option in WorkspacePaymentOption.objects.filter(workspace=workspace)}
    options = []
    for method, name, description in PAYMENT_METHODS:
        options.append({
            'method': method,
            'name': name,
            'description': description,
            'option': existing.get(method),
            'online': method in {'card', 'stripe', 'paypal', 'paysimple'},
        })
    quickbooks = AccountingConnection.objects.filter(workspace=workspace, provider='quickbooks').first()
    return render(request, 'finance_payment_settings.html', {
        'payment_options': options,
        'quickbooks': quickbooks,
    })


@login_required
def finance_job_costing_view(request):
    workspace = _finance_workspace(request)
    if workspace is None:
        return redirect('employee_profile')

    jobs = Job.objects.filter(organization=workspace).select_related('account', 'property').prefetch_related(
        'worker_assignments__worker__user',
        'material_runs',
        'invoiced_items',
    ).order_by('-scheduled_start', '-id')[:250]
    rows = []
    totals = {'revenue': Decimal('0'), 'labor': Decimal('0'), 'materials': Decimal('0'), 'margin': Decimal('0')}
    for job in jobs:
        invoiced_revenue = sum((item.total_price for item in job.invoiced_items.all()), Decimal('0'))
        revenue = invoiced_revenue or (job.client_given_price + job.additional_expense + job.client_tip)
        labor = sum(
            (assignment_time_and_earnings(assignment)['earnings'] for assignment in job.worker_assignments.all()),
            Decimal('0'),
        )
        materials = sum((run.material_cost for run in job.material_runs.all()), Decimal('0'))
        margin = revenue - labor - materials
        rows.append({
            'job': job,
            'revenue': revenue,
            'labor': labor,
            'materials': materials,
            'cost': labor + materials,
            'margin': margin,
        })
        totals['revenue'] += revenue
        totals['labor'] += labor
        totals['materials'] += materials
        totals['margin'] += margin
    return render(request, 'finance_job_costing.html', {'job_cost_rows': rows, 'cost_totals': totals})

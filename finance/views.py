from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db.models import Sum
from django.shortcuts import redirect, render

from crm.models.contacts import PaymentMethod
from finance.models import Invoice
from organizations.permissions import user_can_manage_workspace, worker_profile_for_workspace


@login_required
def finance_overview_view(request):
    active_org = getattr(request, 'active_organization', None)
    if not user_can_manage_workspace(request.user, active_org):
        if worker_profile_for_workspace(request.user, active_org):
            return redirect('employee_profile')
        raise PermissionDenied('Only workspace admins can access Finance.')

    if active_org:
        invoices = Invoice.objects.filter(organization=active_org).select_related('account')
        payment_methods = PaymentMethod.objects.filter(account__organization=active_org)
    else:
        invoices = Invoice.objects.none()
        payment_methods = PaymentMethod.objects.none()

    totals = invoices.aggregate(total_billed=Sum('total_amount'))
    open_invoices = invoices.exclude(status__in=['paid', 'canceled'])

    context = {
        'invoices': invoices.order_by('-issue_date', '-id')[:12],
        'finance_stats': {
            'invoice_count': invoices.count(),
            'open_invoice_count': open_invoices.count(),
            'payment_method_count': payment_methods.count(),
            'total_billed': totals.get('total_billed') or 0,
            'open_balance': open_invoices.aggregate(total=Sum('total_amount')).get('total') or 0,
        },
    }
    return render(request, 'finance_overview.html', context)

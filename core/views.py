from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db.models import Sum
from django.shortcuts import redirect, render

from crm.models.contacts import Account, Contact, PaymentMethod, Property
from finance.models import Invoice
from fsm.models import Job, JobAssignment
from organizations.models import WorkerProfile
from organizations.permissions import user_can_manage_workspace, worker_profile_for_workspace


@login_required
def reports_view(request):
    active_org = getattr(request, 'active_organization', None)
    if not user_can_manage_workspace(request.user, active_org):
        if worker_profile_for_workspace(request.user, active_org):
            return redirect('employee_profile')
        raise PermissionDenied('Only workspace admins can access Reports.')

    if active_org:
        accounts = Account.objects.filter(organization=active_org)
        contacts = Contact.objects.filter(account__organization=active_org)
        properties = Property.objects.filter(account__organization=active_org)
        payment_methods = PaymentMethod.objects.filter(account__organization=active_org)
        jobs = Job.objects.filter(organization=active_org)
        workers = WorkerProfile.objects.filter(workspaces=active_org)
        assignments = JobAssignment.objects.filter(job__organization=active_org, worker__workspaces=active_org)
        invoices = Invoice.objects.filter(organization=active_org)
    else:
        accounts = Account.objects.none()
        contacts = Contact.objects.none()
        properties = Property.objects.none()
        payment_methods = PaymentMethod.objects.none()
        jobs = Job.objects.none()
        workers = WorkerProfile.objects.none()
        assignments = JobAssignment.objects.none()
        invoices = Invoice.objects.none()

    context = {
        'report_stats': {
            'accounts': accounts.count(),
            'contacts': contacts.count(),
            'properties': properties.count(),
            'payment_methods': payment_methods.count(),
            'pending_jobs': jobs.filter(status='pending').count(),
            'dispatched_jobs': jobs.filter(status='dispatched').count(),
            'completed_jobs': jobs.filter(status='completed').count(),
            'workers': workers.count(),
            'active_assignments': assignments.exclude(job__status__in=['completed', 'canceled']).count(),
            'invoice_count': invoices.count(),
            'open_balance': invoices.exclude(status__in=['paid', 'canceled']).aggregate(total=Sum('total_amount')).get('total') or 0,
        },
    }
    return render(request, 'reports.html', context)

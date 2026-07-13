from django.shortcuts import render
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.shortcuts import redirect
from fsm.models import Job
from organizations.models import CustomField
from organizations.permissions import user_can_manage_workspace, worker_profile_for_workspace
from crm.models.contacts import Account, Contact, PaymentMethod, Property

# Existing views
from .dashboard import dashboard_view
from .leads import leads_list_view

# New views
@login_required
def crm_accounts_view(request, section='accounts'):
    active_org = getattr(request, 'active_organization', None)
    if not user_can_manage_workspace(request.user, active_org):
        if worker_profile_for_workspace(request.user, active_org):
            return redirect('employee_profile')
        raise PermissionDenied('Only workspace admins can access CRM.')

    requested_section = request.GET.get('section') or section
    allowed_sections = {'accounts', 'contacts', 'properties', 'payment_methods'}
    if requested_section not in allowed_sections:
        requested_section = 'accounts'

    if active_org:
        accounts = Account.objects.filter(organization=active_org)
        contacts = Contact.objects.filter(organization=active_org)
        properties = Property.objects.filter(account__organization=active_org)
        payment_methods = PaymentMethod.objects.filter(account__organization=active_org)
        open_jobs = Job.objects.filter(organization=active_org).exclude(status__in=['completed', 'canceled'])
        custom_fields = CustomField.objects.filter(workspace=active_org).order_by('target_model', 'label')
    else:
        accounts = Account.objects.none()
        contacts = Contact.objects.none()
        properties = Property.objects.none()
        payment_methods = PaymentMethod.objects.none()
        open_jobs = Job.objects.none()
        custom_fields = CustomField.objects.none()

    context = {
        'crm_stats': {
            'accounts': accounts.count(),
            'contacts': contacts.count(),
            'properties': properties.count(),
            'payment_methods': payment_methods.count(),
            'open_jobs': open_jobs.count(),
        },
        'crm_initial_tab': requested_section,
        'crm_custom_fields': [
            {
                'target_model': field.target_model,
                'label': field.label,
                'internal_name': field.internal_name,
                'field_type': field.field_type,
                'options': field.options,
                'is_required': field.is_required,
            }
            for field in custom_fields
        ],
    }
    return render(request, 'crm_accounts.html', context)

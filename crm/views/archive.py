from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.shortcuts import render

from crm.models.contacts import Account, Contact
from organizations.permissions import user_can_manage_workspace


@login_required
def crm_archive_view(request):
    workspace = getattr(request, 'active_organization', None)
    if not user_can_manage_workspace(request.user, workspace):
        raise PermissionDenied('You do not have access to this CRM archive.')
    return render(request, 'crm_archive.html', {
        'archived_account_count': Account.objects.filter(
            organization=workspace, archived_at__isnull=False,
        ).count(),
        'archived_contact_count': Contact.objects.filter(
            organization=workspace, archived_at__isnull=False,
        ).count(),
    })

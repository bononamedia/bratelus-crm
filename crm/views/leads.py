from django.shortcuts import render
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.shortcuts import redirect
from organizations.permissions import user_can_manage_workspace, worker_profile_for_workspace

@login_required
def leads_list_view(request):
    active_org = getattr(request, 'active_organization', None)
    if not user_can_manage_workspace(request.user, active_org):
        if worker_profile_for_workspace(request.user, active_org):
            return redirect('employee_profile')
        raise PermissionDenied('Only workspace admins can access leads.')

    # For now, this just renders the HTML page. 
    # JavaScript on the page will fetch the actual data from the API!
    return render(request, 'leads.html')

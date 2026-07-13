from django.db.models import Q

from organizations.models import Workspace
from organizations.permissions import (
    user_can_manage_workspace,
    worker_profile_for_workspace,
    workspace_membership_for_user,
    workspace_role_label,
)

def organization_context(request):
    """Injects the user's active organization and a list of all their organizations into every template."""
    if not request.user.is_authenticated:
        return {}

    # 1. Get the active organization set by our Middleware
    active_org = getattr(request, 'active_organization', None)

    user_orgs = Workspace.objects.filter(
        Q(members__user=request.user, members__is_active=True) |
        Q(workers__user=request.user)
    ).distinct()

    active_membership = workspace_membership_for_user(request.user, active_org)
    active_worker_profile = worker_profile_for_workspace(request.user, active_org)
    can_manage_active_org = user_can_manage_workspace(request.user, active_org)

    return {
        'active_org': active_org,
        'user_organizations': user_orgs,
        'active_membership': active_membership,
        'active_worker_profile': active_worker_profile,
        'active_role_label': workspace_role_label(request.user, active_org),
        'can_manage_active_org': can_manage_active_org,
        'is_platform_admin': request.user.is_staff or request.user.is_superuser,
        'is_workspace_employee': bool(active_worker_profile or active_membership),
    }

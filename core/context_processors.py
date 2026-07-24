from django.db.models import Q

from organizations.models import UserAppearancePreference, Workspace
from organizations.permissions import (
    user_can_export_data,
    user_can_manage_people,
    user_can_manage_setup,
    user_can_manage_workspace,
    user_can_purge_crm,
    user_can_view_billing,
    user_is_workspace_admin,
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

    if request.user.is_superuser:
        user_orgs = Workspace.objects.all()
    else:
        user_orgs = Workspace.objects.filter(
            Q(members__user=request.user, members__is_active=True) |
            Q(workers__user=request.user)
        ).distinct()

    active_membership = workspace_membership_for_user(request.user, active_org)
    active_worker_profile = worker_profile_for_workspace(request.user, active_org)
    can_manage_active_org = user_can_manage_workspace(request.user, active_org)
    ui_theme = UserAppearancePreference.objects.filter(user=request.user).values_list('theme', flat=True).first() or 'blue'

    return {
        'active_org': active_org,
        'user_organizations': user_orgs,
        'active_membership': active_membership,
        'active_worker_profile': active_worker_profile,
        'active_role_label': workspace_role_label(request.user, active_org),
        'can_manage_active_org': can_manage_active_org,
        'can_manage_people': user_can_manage_people(request.user, active_org),
        'can_manage_setup': user_can_manage_setup(request.user, active_org),
        'can_view_billing': user_can_view_billing(request.user, active_org),
        'can_export_data': user_can_export_data(request.user, active_org),
        'can_purge_crm': user_can_purge_crm(request.user, active_org),
        'is_workspace_admin': user_is_workspace_admin(request.user, active_org),
        'is_platform_admin': request.user.is_superuser,
        'is_workspace_employee': bool(active_worker_profile or active_membership),
        'ui_theme': ui_theme,
    }

from django.db.models import Q

from .models import CustomerAccountMember, WorkerProfile, Workspace, WorkspaceMember


OPERATIONAL_ROLES = ('admin', 'manager', 'employee')


def customer_account_membership_for_user(user, customer_account):
    if not user.is_authenticated or not customer_account:
        return None
    return CustomerAccountMember.objects.filter(
        account=customer_account,
        user=user,
        is_active=True,
    ).first()


def user_can_manage_customer_account(user, customer_account):
    if user.is_superuser:
        return True
    membership = customer_account_membership_for_user(user, customer_account)
    return bool(membership and membership.role in ('owner', 'admin', 'manager'))


def user_is_customer_account_admin(user, customer_account):
    if user.is_superuser:
        return True
    membership = customer_account_membership_for_user(user, customer_account)
    return bool(membership and membership.role in ('owner', 'admin'))


def user_can_purge_crm(user, workspace):
    if not user.is_authenticated or not workspace:
        return False
    if user.is_superuser:
        return True
    if workspace.customer_account_id:
        return user_is_customer_account_admin(user, workspace.customer_account)
    return user_is_workspace_admin(user, workspace)


def account_workspaces_for_user(user, workspace):
    """Sibling workspace calendars visible through the same customer account."""
    if not user.is_authenticated or not workspace:
        return Workspace.objects.none()
    if user.is_superuser:
        if workspace.customer_account_id:
            return Workspace.objects.filter(customer_account=workspace.customer_account)
        return Workspace.objects.all()
    account = workspace.customer_account
    if not account or not customer_account_membership_for_user(user, account):
        return Workspace.objects.filter(members__user=user, members__is_active=True).distinct()
    return Workspace.objects.filter(
        customer_account=account,
        members__user=user,
        members__is_active=True,
    ).distinct()


def workspace_membership_for_user(user, workspace):
    if not user.is_authenticated or not workspace:
        return None

    return WorkspaceMember.objects.filter(
        workspace=workspace,
        user=user,
        is_active=True,
    ).first()


def worker_profile_for_workspace(user, workspace):
    if not user.is_authenticated or not workspace:
        return None

    return WorkerProfile.objects.filter(
        Q(user=user),
        Q(workspaces=workspace),
    ).select_related('user').first()


def user_can_manage_workspace(user, workspace):
    if not user.is_authenticated or not workspace:
        return False

    if user.is_superuser:
        return True

    membership = workspace_membership_for_user(user, workspace)
    if membership and membership.role in OPERATIONAL_ROLES:
        return True

    return False


def user_is_workspace_admin(user, workspace):
    if not user.is_authenticated or not workspace:
        return False
    if user.is_superuser:
        return True
    membership = workspace_membership_for_user(user, workspace)
    return bool(membership and membership.role == 'admin')


def user_can_manage_people(user, workspace):
    if user.is_superuser:
        return True
    membership = workspace_membership_for_user(user, workspace)
    return bool(membership and membership.role in ('admin', 'manager'))


def user_can_manage_setup(user, workspace):
    return user_is_workspace_admin(user, workspace)


def user_can_view_billing(user, workspace):
    if user.is_superuser:
        return True
    membership = workspace_membership_for_user(user, workspace)
    return bool(
        membership and (
            membership.role == 'admin' or
            (membership.role == 'manager' and membership.can_view_billing)
        )
    )


def user_can_export_data(user, workspace):
    return user_is_workspace_admin(user, workspace)


def workspace_role_label(user, workspace):
    if not user.is_authenticated:
        return 'Signed out'

    if user.is_superuser:
        return 'Platform Superadmin'

    membership = workspace_membership_for_user(user, workspace)
    if membership:
        return membership.get_role_display()

    worker_profile = worker_profile_for_workspace(user, workspace)
    if worker_profile:
        return 'Workspace Admin' if worker_profile.is_admin else 'Employee'

    return 'Member'

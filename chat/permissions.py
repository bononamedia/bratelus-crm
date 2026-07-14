from organizations.models import CustomerAccountMember


def account_for_request(request):
    workspace = getattr(request, 'active_organization', None)
    return getattr(workspace, 'customer_account', None)


def user_in_account(user, account):
    if not user.is_authenticated or not account:
        return False
    if user.is_superuser:
        return True
    return CustomerAccountMember.objects.filter(account=account, user=user, is_active=True).exists()

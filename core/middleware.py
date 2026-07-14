from django.db.models import Q
from django.shortcuts import redirect

from organizations.models import CustomerAccountMember, EmployeeDocument, WorkerProfile, Workspace

class ActiveOrganizationMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.user.is_authenticated:
            if request.user.is_superuser:
                user_workspaces = Workspace.objects.all()
            else:
                user_workspaces = Workspace.objects.filter(
                    Q(members__user=request.user, members__is_active=True) |
                    Q(workers__user=request.user)
                ).distinct()

            active_org_id = request.session.get('active_org_id')
            active_org = None

            if active_org_id:
                active_org = user_workspaces.filter(id=active_org_id).first()
                if not active_org:
                    request.session.pop('active_org_id', None)

            if not active_org:
                active_org = user_workspaces.order_by('created_at', 'id').first()
                if active_org:
                    request.session['active_org_id'] = str(active_org.id)

            request.active_organization = active_org

            onboarding_allowed_paths = (
                '/me/',
                '/accounts/logout/',
                '/accounts/login/',
                '/api/passkeys/',
                '/static/',
            )
            if active_org and not request.path.startswith(onboarding_allowed_paths):
                account_member = CustomerAccountMember.objects.filter(
                    account=active_org.customer_account,
                    user=request.user,
                    is_active=True,
                ).first()
                worker = WorkerProfile.objects.filter(user=request.user).first()
                if account_member and worker:
                    photo_missing = account_member.photo_required and not worker.photo
                    license_missing = account_member.drivers_license_required and not EmployeeDocument.objects.filter(
                        account=active_org.customer_account,
                        user=request.user,
                        document_type='drivers_license',
                        status__in=['pending', 'approved'],
                    ).exists()
                    if photo_missing or license_missing:
                        return redirect('employee_profile')
        else:
            request.active_organization = None

        response = self.get_response(request)
        return response

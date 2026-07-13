from django.db.models import Q

from organizations.models import Workspace

class ActiveOrganizationMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.user.is_authenticated:
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
                active_org = user_workspaces.first()
                if active_org:
                    request.session['active_org_id'] = str(active_org.id)

            request.active_organization = active_org
        else:
            request.active_organization = None

        response = self.get_response(request)
        return response

from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework import status
from rest_framework.exceptions import PermissionDenied, ValidationError
from .serializers import (
    AccountSerializer,
    ContactSerializer,
    JobSerializer,
    PaymentMethodSerializer,
    PropertySerializer,
    WorkerSerializer,
)
from organizations.models import WorkerProfile
from organizations.permissions import user_can_manage_workspace
from crm.models.contacts import Account, Contact, PaymentMethod, Property
from fsm.models import Job, JobAssignment

class BaseWorkspaceViewSet(viewsets.ModelViewSet):
    """
    SECURITY LAYER: 
    Automatically filters all API requests to only show data 
    belonging to the user's active organization.
    """
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        # 1. The Middleware automatically attaches the active organization for us!
        active_org = getattr(self.request, 'active_organization', None)
        
        # Security fallback: If they somehow don't have an active org, return nothing.
        if not active_org:
            return self.queryset.none()

        # 2. Return only the data for that active organization!
        return self.queryset.filter(organization=active_org)


class AccountViewSet(BaseWorkspaceViewSet):
    queryset = Account.objects.all()
    serializer_class = AccountSerializer

    def get_queryset(self):
        if not user_can_manage_workspace(self.request.user, getattr(self.request, 'active_organization', None)):
            return self.queryset.none()
        return super().get_queryset().prefetch_related('contacts', 'properties')

    def perform_create(self, serializer):
        if not user_can_manage_workspace(self.request.user, self.request.active_organization):
            raise PermissionDenied('Only workspace admins can manage CRM accounts.')

        # Auto-attach the organization that the user currently has selected in the UI
        serializer.save(organization=self.request.active_organization)


class ContactViewSet(BaseWorkspaceViewSet):
    queryset = Contact.objects.all()
    serializer_class = ContactSerializer
    
    # Contacts don't have a direct organization link, they link through Account
    def get_queryset(self):
        active_org = getattr(self.request, 'active_organization', None)
        if not active_org or not user_can_manage_workspace(self.request.user, active_org):
            return self.queryset.none()
            
        return Contact.objects.filter(account__organization=active_org).select_related('account')

    def perform_create(self, serializer):
        active_org = getattr(self.request, 'active_organization', None)
        if not user_can_manage_workspace(self.request.user, active_org):
            raise PermissionDenied('Only workspace admins can manage CRM contacts.')

        account = serializer.validated_data.get('account')
        if not active_org or account.organization_id != active_org.id:
            raise ValidationError({'account': 'Account must belong to the active organization.'})

        serializer.save()


class PropertyViewSet(BaseWorkspaceViewSet):
    queryset = Property.objects.all()
    serializer_class = PropertySerializer

    def get_queryset(self):
        active_org = getattr(self.request, 'active_organization', None)
        if not active_org or not user_can_manage_workspace(self.request.user, active_org):
            return self.queryset.none()

        return Property.objects.filter(account__organization=active_org).select_related('account')

    def perform_create(self, serializer):
        active_org = getattr(self.request, 'active_organization', None)
        if not user_can_manage_workspace(self.request.user, active_org):
            raise PermissionDenied('Only workspace admins can manage CRM properties.')

        account = serializer.validated_data.get('account')
        if not active_org or account.organization_id != active_org.id:
            raise ValidationError({'account': 'Account must belong to the active organization.'})

        serializer.save()


class PaymentMethodViewSet(viewsets.ModelViewSet):
    queryset = PaymentMethod.objects.all()
    serializer_class = PaymentMethodSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        active_org = getattr(self.request, 'active_organization', None)
        if not active_org or not user_can_manage_workspace(self.request.user, active_org):
            return self.queryset.none()

        return PaymentMethod.objects.filter(account__organization=active_org).select_related(
            'account',
            'assigned_property',
        )

    def _validate_workspace_links(self, serializer):
        active_org = getattr(self.request, 'active_organization', None)
        if not user_can_manage_workspace(self.request.user, active_org):
            raise PermissionDenied('Only workspace admins can manage payment methods.')

        account = serializer.validated_data.get('account') or getattr(serializer.instance, 'account', None)
        assigned_property = serializer.validated_data.get('assigned_property')
        if assigned_property is None and serializer.instance:
            assigned_property = serializer.instance.assigned_property

        if not active_org or account.organization_id != active_org.id:
            raise ValidationError({'account': 'Account must belong to the active organization.'})
        if assigned_property and assigned_property.account.organization_id != active_org.id:
            raise ValidationError({'assigned_property': 'Property must belong to the active organization.'})
        if assigned_property and assigned_property.account_id != account.id:
            raise ValidationError({'assigned_property': 'Property must belong to the selected account.'})

    def perform_create(self, serializer):
        self._validate_workspace_links(serializer)
        serializer.save()

    def perform_update(self, serializer):
        self._validate_workspace_links(serializer)
        serializer.save()


class JobViewSet(BaseWorkspaceViewSet):
    queryset = Job.objects.all()
    serializer_class = JobSerializer
    
    def get_queryset(self):
        active_org = getattr(self.request, 'active_organization', None)
        if not active_org:
            return self.queryset.none()

        if not user_can_manage_workspace(self.request.user, active_org):
            try:
                worker_profile = self.request.user.workerprofile
            except WorkerProfile.DoesNotExist:
                return self.queryset.none()

            return (
                Job.objects.filter(organization=active_org, worker_assignments__worker=worker_profile)
                .select_related('account', 'property', 'required_skill', 'service_zone')
                .prefetch_related('worker_assignments__worker__user')
                .distinct()
            )

        return (
            Job.objects.filter(organization=active_org)
            .select_related('account', 'property', 'required_skill', 'service_zone')
            .prefetch_related('worker_assignments__worker__user')
        )

    def _require_manager(self):
        if not user_can_manage_workspace(self.request.user, getattr(self.request, 'active_organization', None)):
            raise PermissionDenied('Only workspace admins can manage dispatch jobs from this API.')

    def create(self, request, *args, **kwargs):
        self._require_manager()
        return super().create(request, *args, **kwargs)

    def update(self, request, *args, **kwargs):
        self._require_manager()
        return super().update(request, *args, **kwargs)

    def partial_update(self, request, *args, **kwargs):
        self._require_manager()
        return super().partial_update(request, *args, **kwargs)

    def destroy(self, request, *args, **kwargs):
        self._require_manager()
        return super().destroy(request, *args, **kwargs)

    def perform_create(self, serializer):
        serializer.save(organization=self.request.active_organization)

    @action(detail=True, methods=['post'], url_path='assign-worker')
    def assign_worker(self, request, pk=None):
        active_org = getattr(request, 'active_organization', None)
        if not active_org:
            return Response(
                {'detail': 'Select an organization before assigning workers.'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if not user_can_manage_workspace(request.user, active_org):
            return Response(
                {'detail': 'Only workspace admins can assign workers.'},
                status=status.HTTP_403_FORBIDDEN,
            )

        worker_id = request.data.get('worker_id')
        worker = WorkerProfile.objects.filter(id=worker_id, workspaces=active_org).first()
        if not worker:
            return Response(
                {'worker_id': 'Worker must belong to the active organization.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        job = self.get_object()
        assignment, created = JobAssignment.objects.get_or_create(
            job=job,
            worker=worker,
            defaults={
                'is_primary_worker': not job.worker_assignments.exists(),
            },
        )

        make_primary = request.data.get('is_primary_worker')
        if make_primary in [True, 'true', 'True', '1', 1]:
            job.worker_assignments.exclude(id=assignment.id).update(is_primary_worker=False)
            assignment.is_primary_worker = True
            assignment.save(update_fields=['is_primary_worker'])

        if job.status == 'pending':
            job.status = 'dispatched'
            job.save(update_fields=['status'])

        serializer = self.get_serializer(job)
        response_status = status.HTTP_201_CREATED if created else status.HTTP_200_OK
        return Response(serializer.data, status=response_status)

    @action(detail=True, methods=['post'], url_path='unassign-worker')
    def unassign_worker(self, request, pk=None):
        active_org = getattr(request, 'active_organization', None)
        if not active_org:
            return Response(
                {'detail': 'Select an organization before changing assignments.'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if not user_can_manage_workspace(request.user, active_org):
            return Response(
                {'detail': 'Only workspace admins can change assignments.'},
                status=status.HTTP_403_FORBIDDEN,
            )

        job = self.get_object()
        if job.status in ['in_progress', 'completed']:
            return Response(
                {'detail': 'Crew cannot be removed after a job is in progress or completed.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        worker_id = request.data.get('worker_id')
        assignment = JobAssignment.objects.filter(
            job=job,
            worker_id=worker_id,
            worker__workspaces=active_org,
        ).first()

        if not assignment:
            return Response(
                {'worker_id': 'Worker is not assigned to this job.'},
                status=status.HTTP_404_NOT_FOUND,
            )

        was_primary = assignment.is_primary_worker
        assignment.delete()

        remaining_assignments = job.worker_assignments.order_by('id')
        if was_primary and remaining_assignments.exists():
            next_assignment = remaining_assignments.first()
            next_assignment.is_primary_worker = True
            next_assignment.save(update_fields=['is_primary_worker'])

        if not remaining_assignments.exists() and job.status in ['dispatched', 'accepted', 'en_route']:
            job.status = 'pending'
            job.save(update_fields=['status'])

        serializer = self.get_serializer(job)
        return Response(serializer.data, status=status.HTTP_200_OK)


class WorkerViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = WorkerProfile.objects.all()
    serializer_class = WorkerSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        active_org = getattr(self.request, 'active_organization', None)
        if not active_org:
            return self.queryset.none()

        if not user_can_manage_workspace(self.request.user, active_org):
            return (
                WorkerProfile.objects.filter(user=self.request.user, workspaces=active_org)
                .select_related('user')
            )

        return (
            WorkerProfile.objects.filter(workspaces=active_org)
            .select_related('user')
            .order_by('user__first_name', 'user__last_name', 'user__username')
        )

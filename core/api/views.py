import re

from django.db import transaction
from django.db.models import Q
from django.utils.text import slugify
from django.utils import timezone
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.pagination import PageNumberPagination
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
from organizations.models import WorkerProfile, Workspace
from organizations.permissions import user_can_manage_workspace, user_can_purge_crm
from crm.models.contacts import Account, Contact, PaymentMethod, Property
from crm.services.contacts import duplicate_account_bundle, duplicate_contact
from fsm.models import Job, JobAssignment


class ContactPagination(PageNumberPagination):
    page_size = 100
    page_size_query_param = 'page_size'
    max_page_size = 25000

    def get_page_size(self, request):
        if request.query_params.get(self.page_size_query_param) == 'all':
            return self.max_page_size
        return super().get_page_size(request)


def contact_search_query(query):
    query = (query or '').strip()
    if not query:
        return Q()

    filters = (
        Q(first_name__icontains=query) |
        Q(last_name__icontains=query) |
        Q(email__icontains=query) |
        Q(secondary_email__icontains=query) |
        Q(phone__icontains=query) |
        Q(mobile__icontains=query)
    )
    digits = ''.join(character for character in query if character.isdigit())
    if len(digits) >= 3:
        flexible_phone = r'\D*'.join(re.escape(character) for character in digits)
        filters |= Q(phone__iregex=flexible_phone) | Q(mobile__iregex=flexible_phone)
    return filters

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
        return super().get_queryset().filter(archived_at__isnull=True).prefetch_related('contacts', 'properties')

    def perform_create(self, serializer):
        if not user_can_manage_workspace(self.request.user, self.request.active_organization):
            raise PermissionDenied('Only workspace admins can manage CRM accounts.')

        # Auto-attach the organization that the user currently has selected in the UI
        serializer.save(organization=self.request.active_organization)

    @action(detail=True, methods=['get'], url_path='configuration')
    def configuration(self, request, pk=None):
        account = self.get_object()
        primary_contact = account.contacts.filter(archived_at__isnull=True).order_by('-is_primary', 'id').first()
        primary_property = account.properties.order_by('id').first()
        default_payment = account.payment_methods.order_by('-is_default', 'id').first()
        return Response({
            'account': self.get_serializer(account).data,
            'contact': ContactSerializer(primary_contact).data if primary_contact else None,
            'property': PropertySerializer(primary_property).data if primary_property else None,
            'payment_method': PaymentMethodSerializer(default_payment).data if default_payment else None,
        })

    @action(detail=False, methods=['post'], url_path='create-bundle')
    @transaction.atomic
    def create_bundle(self, request):
        workspace = getattr(request, 'active_organization', None)
        if not user_can_manage_workspace(request.user, workspace):
            raise PermissionDenied('Only workspace admins can manage CRM accounts.')

        account_serializer = self.get_serializer(data=request.data.get('account') or {})
        account_serializer.is_valid(raise_exception=True)
        account = account_serializer.save(organization=workspace)

        created = {'account': account_serializer.data}
        contact_data = request.data.get('contact')
        if contact_data:
            contact_serializer = ContactSerializer(data={**contact_data, 'account': account.id})
            contact_serializer.is_valid(raise_exception=True)
            contact_serializer.save(organization=workspace)
            created['contact'] = contact_serializer.data

        property_record = None
        property_data = request.data.get('property')
        if property_data:
            property_serializer = PropertySerializer(data={**property_data, 'account': account.id})
            property_serializer.is_valid(raise_exception=True)
            property_record = property_serializer.save()
            created['property'] = property_serializer.data

        payment_data = request.data.get('payment_method')
        if payment_data:
            payment_payload = {**payment_data, 'account': account.id}
            if payment_payload.pop('use_created_property', False) and property_record:
                payment_payload['assigned_property'] = property_record.id
            payment_serializer = PaymentMethodSerializer(data=payment_payload)
            payment_serializer.is_valid(raise_exception=True)
            payment_serializer.save()
            created['payment_method'] = payment_serializer.data

        return Response(created, status=status.HTTP_201_CREATED)

    def destroy(self, request, *args, **kwargs):
        account = self.get_object()
        account.archived_at = timezone.now()
        account.archived_by = request.user
        account.save(update_fields=['archived_at', 'archived_by'])
        return Response(status=status.HTTP_204_NO_CONTENT)

    @action(detail=False, methods=['get'], url_path='archived')
    def archived(self, request):
        workspace = getattr(request, 'active_organization', None)
        records = Account.objects.filter(organization=workspace, archived_at__isnull=False).select_related(
            'archived_by',
        ).prefetch_related('contacts', 'properties').order_by('-archived_at')
        return Response(self.get_serializer(records, many=True).data)

    def _archived_account(self, request, pk):
        workspace = getattr(request, 'active_organization', None)
        return Account.objects.filter(id=pk, organization=workspace, archived_at__isnull=False).first()

    @action(detail=True, methods=['post'], url_path='restore')
    def restore(self, request, pk=None):
        account = self._archived_account(request, pk)
        if not account:
            return Response({'detail': 'Archived account not found.'}, status=status.HTTP_404_NOT_FOUND)
        account.archived_at = None
        account.archived_by = None
        account.save(update_fields=['archived_at', 'archived_by'])
        return Response(self.get_serializer(account).data)

    @action(detail=True, methods=['delete'], url_path='purge')
    def purge(self, request, pk=None):
        workspace = getattr(request, 'active_organization', None)
        if not user_can_purge_crm(request.user, workspace):
            raise PermissionDenied('Only account owners and administrators can permanently delete CRM records.')
        account = self._archived_account(request, pk)
        if not account:
            return Response({'detail': 'Archived account not found.'}, status=status.HTTP_404_NOT_FOUND)
        if account.jobs.exists():
            raise ValidationError({'detail': 'This account has job history and cannot be permanently deleted.'})
        account.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)

    @action(detail=True, methods=['post'], url_path='duplicate-to-workspace')
    def duplicate_to_workspace(self, request, pk=None):
        source = self.get_object()
        target_query = Workspace.objects.exclude(id=source.organization_id)
        if not request.user.is_superuser:
            target_query = target_query.filter(
                members__user=request.user,
                members__is_active=True,
                members__role__in=('admin', 'manager', 'employee'),
            ).distinct()
        target = target_query.filter(id=request.data.get('workspace_id')).first()
        if not target:
            raise ValidationError({'workspace_id': 'Choose a workspace you can access.'})
        account, created, copied = duplicate_account_bundle(source, target)
        payload = self.get_serializer(account).data
        payload.update({'created': created, 'copied': copied})
        return Response(payload, status=status.HTTP_201_CREATED if created else status.HTTP_200_OK)


class ContactViewSet(BaseWorkspaceViewSet):
    queryset = Contact.objects.all()
    serializer_class = ContactSerializer
    pagination_class = ContactPagination
    
    # Contacts don't have a direct organization link, they link through Account
    def get_queryset(self):
        active_org = getattr(self.request, 'active_organization', None)
        if not active_org or not user_can_manage_workspace(self.request.user, active_org):
            return self.queryset.none()
            
        return (
            Contact.objects.filter(organization=active_org, archived_at__isnull=True)
            .filter(Q(account__isnull=True) | Q(account__archived_at__isnull=True))
            .filter(contact_search_query(self.request.query_params.get('search')))
            .select_related('account', 'organization')
            .order_by('last_name', 'first_name', 'id')
        )

    def perform_create(self, serializer):
        active_org = getattr(self.request, 'active_organization', None)
        if not user_can_manage_workspace(self.request.user, active_org):
            raise PermissionDenied('Only workspace admins can manage CRM contacts.')

        account = serializer.validated_data.get('account')
        if account and account.organization_id != active_org.id:
            raise ValidationError({'account': 'Account must belong to the active organization.'})

        serializer.save(organization=active_org)

    def destroy(self, request, *args, **kwargs):
        contact = self.get_object()
        contact.archived_at = timezone.now()
        contact.archived_by = request.user
        contact.save(update_fields=['archived_at', 'archived_by'])
        return Response(status=status.HTTP_204_NO_CONTENT)

    @action(detail=False, methods=['get'], url_path='archived')
    def archived(self, request):
        workspace = getattr(request, 'active_organization', None)
        records = Contact.objects.filter(
            organization=workspace, archived_at__isnull=False,
        ).select_related('account', 'organization', 'archived_by').order_by('-archived_at')
        page = self.paginate_queryset(records)
        if page is not None:
            return self.get_paginated_response(self.get_serializer(page, many=True).data)
        return Response(self.get_serializer(records, many=True).data)

    def _archived_contact(self, request, pk):
        workspace = getattr(request, 'active_organization', None)
        return Contact.objects.filter(id=pk, organization=workspace, archived_at__isnull=False).first()

    @action(detail=True, methods=['post'], url_path='restore')
    def restore(self, request, pk=None):
        contact = self._archived_contact(request, pk)
        if not contact:
            return Response({'detail': 'Archived contact not found.'}, status=status.HTTP_404_NOT_FOUND)
        contact.archived_at = None
        contact.archived_by = None
        contact.save(update_fields=['archived_at', 'archived_by'])
        return Response(self.get_serializer(contact).data)

    @action(detail=True, methods=['delete'], url_path='purge')
    def purge(self, request, pk=None):
        workspace = getattr(request, 'active_organization', None)
        if not user_can_purge_crm(request.user, workspace):
            raise PermissionDenied('Only account owners and administrators can permanently delete CRM records.')
        contact = self._archived_contact(request, pk)
        if not contact:
            return Response({'detail': 'Archived contact not found.'}, status=status.HTTP_404_NOT_FOUND)
        contact.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)

    def perform_update(self, serializer):
        active_org = getattr(self.request, 'active_organization', None)
        if not user_can_manage_workspace(self.request.user, active_org):
            raise PermissionDenied('Only workspace admins can manage CRM contacts.')

        account = serializer.validated_data.get('account', serializer.instance.account)
        if account and account.organization_id != active_org.id:
            raise ValidationError({'account': 'Account must belong to the active organization.'})
        serializer.save(organization=active_org)

    def _available_target_workspaces(self):
        source = getattr(self.request, 'active_organization', None)
        if self.request.user.is_superuser:
            return Workspace.objects.exclude(id=getattr(source, 'id', None)).order_by('name')
        return Workspace.objects.filter(
            members__user=self.request.user,
            members__is_active=True,
            members__role__in=('admin', 'manager', 'employee'),
        ).exclude(id=getattr(source, 'id', None)).distinct().order_by('name')

    @action(detail=True, methods=['post'], url_path='duplicate-to-workspace')
    def duplicate_to_workspace(self, request, pk=None):
        source = self.get_object()
        target = self._available_target_workspaces().filter(
            id=request.data.get('workspace_id'),
        ).first()
        if not target:
            raise ValidationError({'workspace_id': 'Choose a workspace you can access.'})
        copy, created = duplicate_contact(source, target)
        payload = self.get_serializer(copy).data
        payload['created'] = created
        return Response(payload, status=status.HTTP_201_CREATED if created else status.HTTP_200_OK)

    @staticmethod
    def _workspace_match(label, workspaces):
        normalized = slugify(label or '')
        if not normalized:
            return None
        exact = [
            workspace for workspace in workspaces
            if normalized in {slugify(workspace.name), workspace.slug}
        ]
        if len(exact) == 1:
            return exact[0]
        prefix = [
            workspace for workspace in workspaces
            if slugify(workspace.name).startswith(normalized) or normalized.startswith(slugify(workspace.name))
        ]
        return prefix[0] if len(prefix) == 1 else None

    def _workspace_distribution(self):
        source_workspace = getattr(self.request, 'active_organization', None)
        workspaces = list(Workspace.objects.all().order_by('name'))
        groups = {}
        blank = same_workspace = unknown = 0
        unknown_labels = set()
        contacts = Contact.objects.filter(organization=source_workspace, archived_at__isnull=True).select_related('organization')
        for contact in contacts.iterator(chunk_size=500):
            label = str(
                ((contact.custom_data or {}).get('zoho_fields') or {}).get('Workspace') or ''
            ).strip()
            if not label:
                blank += 1
                continue
            target = self._workspace_match(label, workspaces)
            if not target:
                unknown += 1
                unknown_labels.add(label)
                continue
            if target.id == source_workspace.id:
                same_workspace += 1
                continue
            group = groups.setdefault(target.id, {
                'workspace': target,
                'source_label': label,
                'contacts': [],
            })
            group['contacts'].append(contact)
        return {
            'groups': groups,
            'blank': blank,
            'same_workspace': same_workspace,
            'unknown': unknown,
            'unknown_labels': sorted(unknown_labels),
        }

    @action(detail=False, methods=['get', 'post'], url_path='reconcile-workspaces')
    def reconcile_workspaces(self, request):
        if not request.user.is_superuser:
            raise PermissionDenied('Only the Bratelus platform owner can distribute cross-workspace imports.')
        distribution = self._workspace_distribution()
        preview_groups = [
            {
                'workspace_id': str(group['workspace'].id),
                'workspace_name': group['workspace'].name,
                'source_label': group['source_label'],
                'contacts': len(group['contacts']),
            }
            for group in distribution['groups'].values()
        ]
        preview = {
            'to_duplicate': sum(group['contacts'] for group in preview_groups),
            'same_workspace': distribution['same_workspace'],
            'blank_workspace': distribution['blank'],
            'unknown_workspace': distribution['unknown'],
            'unknown_labels': distribution['unknown_labels'],
            'groups': preview_groups,
        }
        if request.method == 'GET':
            return Response(preview)
        if request.data.get('confirm') is not True:
            raise ValidationError({'confirm': 'Confirm the workspace distribution before continuing.'})
        if distribution['unknown']:
            raise ValidationError({
                'workspace': 'Create or rename the unresolved workspaces before distributing contacts.',
                'unknown_labels': distribution['unknown_labels'],
            })

        created = existing = 0
        with transaction.atomic():
            Workspace.objects.select_for_update().filter(
                id__in=distribution['groups'].keys(),
            ).count()
            for group in distribution['groups'].values():
                for source in group['contacts']:
                    _, was_created = duplicate_contact(source, group['workspace'])
                    created += int(was_created)
                    existing += int(not was_created)
        preview.update({'created': created, 'already_existed': existing})
        return Response(preview, status=status.HTTP_201_CREATED)

    @staticmethod
    def _mailing_address(contact):
        return ', '.join(filter(None, [
            contact.mailing_street.strip(),
            contact.mailing_city.strip(),
            contact.mailing_state.strip(),
            contact.mailing_postal_code.strip(),
            contact.mailing_country.strip(),
        ]))

    @action(detail=False, methods=['get', 'post'], url_path='create-missing-accounts')
    def create_missing_accounts(self, request):
        active_org = getattr(request, 'active_organization', None)
        if not user_can_manage_workspace(request.user, active_org):
            raise PermissionDenied('Only workspace admins can organize imported contacts.')

        accountless = Contact.objects.filter(organization=active_org, account__isnull=True, archived_at__isnull=True)
        address_filter = (
            ~Q(mailing_street='') | ~Q(mailing_city='') | ~Q(mailing_state='') |
            ~Q(mailing_postal_code='') | ~Q(mailing_country='')
        )
        preview = {
            'contacts': accountless.count(),
            'accounts': accountless.count(),
            'properties': accountless.filter(address_filter).count(),
            'without_address': accountless.exclude(address_filter).count(),
        }
        if request.method == 'GET':
            return Response(preview)
        if request.data.get('confirm') is not True:
            raise ValidationError({'confirm': 'Confirm the bulk creation before continuing.'})

        with transaction.atomic():
            contacts = list(
                Contact.objects.select_for_update()
                .filter(organization=active_org, account__isnull=True, archived_at__isnull=True)
                .order_by('id')
            )
            accounts = []
            for contact in contacts:
                account_name = (
                    contact.first_name.strip() or
                    f'{contact.first_name} {contact.last_name}'.strip() or
                    contact.email.strip() or
                    f'Contact {contact.id}'
                )
                mailing_address = self._mailing_address(contact)
                accounts.append(Account(
                    organization=active_org,
                    name=account_name,
                    phone=contact.phone or contact.mobile,
                    email=contact.email,
                    billing_address=mailing_address,
                    billing_street=contact.mailing_street,
                    billing_city=contact.mailing_city,
                    billing_state=contact.mailing_state,
                    billing_postal_code=contact.mailing_postal_code,
                    billing_country=contact.mailing_country or 'United States',
                    shipping_street=contact.mailing_street,
                    shipping_city=contact.mailing_city,
                    shipping_state=contact.mailing_state,
                    shipping_postal_code=contact.mailing_postal_code,
                    shipping_country=contact.mailing_country,
                ))
            Account.objects.bulk_create(accounts, batch_size=500)

            properties = []
            for contact, account in zip(contacts, accounts):
                contact.account = account
                address = self._mailing_address(contact)
                if address:
                    properties.append(Property(
                        account=account,
                        name=account.name,
                        address=address,
                    ))
            Contact.objects.bulk_update(contacts, ['account'], batch_size=500)
            Property.objects.bulk_create(properties, batch_size=500)

        return Response({
            'contacts': len(contacts),
            'accounts': len(accounts),
            'properties': len(properties),
            'without_address': len(contacts) - len(properties),
        }, status=status.HTTP_201_CREATED)

    @action(detail=False, methods=['get'], url_path='global-search')
    def global_search(self, request):
        if not (request.user.is_staff or request.user.is_superuser):
            raise PermissionDenied('Global contact search is restricted to platform administrators.')

        query = (request.query_params.get('search') or '').strip()
        if len(query) < 2:
            raise ValidationError({'search': 'Enter at least 2 characters for global search.'})
        queryset = (
            Contact.objects.filter(archived_at__isnull=True)
            .filter(Q(account__isnull=True) | Q(account__archived_at__isnull=True))
            .filter(contact_search_query(query))
            .select_related('account', 'organization')
            .order_by('last_name', 'first_name', 'organization__name', 'id')
        )
        page = self.paginate_queryset(queryset)
        if page is not None:
            return self.get_paginated_response(self.get_serializer(page, many=True).data)
        return Response(self.get_serializer(queryset, many=True).data)


class PropertyViewSet(BaseWorkspaceViewSet):
    queryset = Property.objects.all()
    serializer_class = PropertySerializer

    def get_queryset(self):
        active_org = getattr(self.request, 'active_organization', None)
        if not active_org or not user_can_manage_workspace(self.request.user, active_org):
            return self.queryset.none()

        return Property.objects.filter(
            account__organization=active_org, account__archived_at__isnull=True,
        ).select_related('account')

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

        return PaymentMethod.objects.filter(
            account__organization=active_org, account__archived_at__isnull=True,
        ).select_related(
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
            .prefetch_related('worker_assignments__worker__user', 'tasks__assigned_worker__user')
        )

    def _require_manager(self):
        if not user_can_manage_workspace(self.request.user, getattr(self.request, 'active_organization', None)):
            raise PermissionDenied('Only workspace admins can manage dispatch jobs from this API.')

    def create(self, request, *args, **kwargs):
        self._require_manager()
        return super().create(request, *args, **kwargs)

    def update(self, request, *args, **kwargs):
        self._require_manager()
        self._validate_editable_job(request)
        return super().update(request, *args, **kwargs)

    def partial_update(self, request, *args, **kwargs):
        self._require_manager()
        self._validate_editable_job(request)
        return super().partial_update(request, *args, **kwargs)

    def destroy(self, request, *args, **kwargs):
        self._require_manager()
        job = self.get_object()
        has_work_history = (
            job.worker_assignments.exists()
            or job.tasks.filter(is_completed=True).exists()
            or job.field_events.exists()
        )
        if job.status != 'pending' or has_work_history:
            return Response(
                {'detail': 'Only an unassigned pending draft can be discarded. Cancel operational jobs instead.'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        return super().destroy(request, *args, **kwargs)

    def _validate_editable_job(self, request):
        job = self.get_object()
        if job.status in {'completed', 'canceled'}:
            raise ValidationError({'detail': 'Completed and canceled jobs are read-only.'})
        if job.status == 'in_progress':
            structural_fields = {
                'title', 'description', 'account', 'property', 'required_skill',
                'service_zone', 'scheduled_start', 'estimated_duration_minutes',
                'completion_mode', 'tasks', 'worker_ids', 'require_location',
                'arrival_radius_meters', 'closeout_instruction',
            }
            if structural_fields.intersection(request.data.keys()):
                raise ValidationError({
                    'detail': 'Clocked-in work cannot be structurally edited. Close the active work first.',
                })

    def perform_create(self, serializer):
        serializer.save(organization=self.request.active_organization)

    @action(detail=True, methods=['post'])
    def cancel(self, request, pk=None):
        self._require_manager()
        job = self.get_object()
        if job.status not in {'pending', 'dispatched', 'accepted', 'en_route'}:
            return Response(
                {'detail': 'Only work that has not started can be canceled.'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if job.worker_assignments.filter(clocked_in_at__isnull=False, clocked_out_at__isnull=True).exists():
            return Response(
                {'detail': 'A crew member is clocked in. Close active work before canceling this job.'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        reason = str(request.data.get('reason', '')).strip()
        if not reason:
            return Response(
                {'reason': 'Enter a cancellation reason for the audit history.'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        audit = dict(job.custom_data or {})
        audit['cancellation'] = {
            'reason': reason[:500],
            'canceled_at': timezone.now().isoformat(),
            'canceled_by_id': request.user.id,
            'canceled_by': request.user.get_full_name() or request.user.username,
        }
        job.custom_data = audit
        job.status = 'canceled'
        job.save(update_fields=['custom_data', 'status'])
        return Response(self.get_serializer(job).data)

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
        workers = WorkerProfile.objects.filter(id=worker_id, workspaces=active_org)
        if active_org.customer_account_id:
            workers = workers.filter(
                user__customer_accounts__account=active_org.customer_account,
                user__customer_accounts__can_work_jobs=True,
                user__customer_accounts__is_active=True,
            )
        worker = workers.first()
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

        workers = WorkerProfile.objects.filter(workspaces=active_org)
        if active_org.customer_account_id:
            workers = workers.filter(
                user__customer_accounts__account=active_org.customer_account,
                user__customer_accounts__can_work_jobs=True,
                user__customer_accounts__is_active=True,
            )
        return workers.select_related('user').distinct().order_by(
            'user__first_name', 'user__last_name', 'user__username'
        )

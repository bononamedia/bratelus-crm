from rest_framework import serializers
from django.core.validators import URLValidator
from django.core.exceptions import ValidationError as DjangoValidationError
from django.contrib.auth.models import User
from django.db import transaction
from organizations.models import WorkerProfile, Skill, ServiceZone
from crm.models.contacts import Account, Contact, PaymentMethod, Property
from fsm.models import Job, JobAssignment, JobTask

# ==========================================
# 1 - TEAMS / WORKFORCE
# ==========================================
class UserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ['id', 'username', 'first_name', 'last_name', 'email']

class WorkerSerializer(serializers.ModelSerializer):
    user = UserSerializer(read_only=True)

    class Meta:
        model = WorkerProfile
        fields = ['id', 'user', 'phone', 'is_admin']


# ==========================================
# 2 - CRM
# ==========================================
class AccountSerializer(serializers.ModelSerializer):
    website = serializers.CharField(required=False, allow_blank=True, max_length=200)
    contact_count = serializers.SerializerMethodField()
    property_count = serializers.SerializerMethodField()

    class Meta:
        model = Account
        fields = [
            'id', 'name', 'phone', 'email', 'website', 'billing_address',
            'billing_street', 'billing_city', 'billing_state', 'billing_postal_code', 'billing_country',
            'shipping_street', 'shipping_city', 'shipping_state', 'shipping_postal_code', 'shipping_country',
            'custom_data', 'contact_count', 'property_count', 'archived_at', 'archived_by',
        ]
        read_only_fields = ['archived_at', 'archived_by']

    def validate_website(self, value):
        from crm.utils import normalize_website
        normalized = normalize_website(value)
        if normalized:
            try:
                URLValidator()(normalized)
            except DjangoValidationError:
                raise serializers.ValidationError('Enter a valid website address.')
        return normalized

    def get_contact_count(self, obj):
        return obj.contacts.count()

    def get_property_count(self, obj):
        return obj.properties.count()

class ContactAccountSerializer(serializers.ModelSerializer):
    class Meta:
        model = Account
        fields = ['id', 'name', 'phone', 'email', 'billing_address']


class ContactSerializer(serializers.ModelSerializer):
    account_details = ContactAccountSerializer(source='account', read_only=True)
    workspace_id = serializers.UUIDField(source='organization_id', read_only=True)
    workspace_name = serializers.CharField(source='organization.name', read_only=True)
    
    class Meta:
        model = Contact
        fields = [
            'id', 'account', 'account_details', 'workspace_id', 'workspace_name',
            'first_name', 'last_name', 'email', 'secondary_email',
            'phone', 'mobile', 'mailing_street', 'mailing_city', 'mailing_state',
            'mailing_postal_code', 'mailing_country', 'lead_source', 'status', 'description',
            'email_opt_out', 'sms_opt_out', 'external_source', 'external_id', 'is_primary', 'custom_data',
            'archived_at', 'archived_by',
        ]
        read_only_fields = ['external_source', 'external_id', 'archived_at', 'archived_by']


class PropertySerializer(serializers.ModelSerializer):
    account_details = AccountSerializer(source='account', read_only=True)

    class Meta:
        model = Property
        fields = [
            'id',
            'account',
            'account_details',
            'name',
            'address',
            'unit_number',
            'gate_code',
            'location_lat',
            'location_lng',
            'custom_data',
        ]


class PaymentMethodSerializer(serializers.ModelSerializer):
    account_details = AccountSerializer(source='account', read_only=True)
    property_name = serializers.CharField(source='assigned_property.name', read_only=True)

    class Meta:
        model = PaymentMethod
        fields = [
            'id',
            'account',
            'account_details',
            'is_default',
            'assigned_property',
            'property_name',
            'card_type',
            'last_four',
            'expiration_date',
        ]


# ==========================================
# 3 - FSM
# ==========================================
class JobSerializer(serializers.ModelSerializer):
    account = serializers.PrimaryKeyRelatedField(queryset=Account.objects.all())
    organization = serializers.PrimaryKeyRelatedField(read_only=True)
    property = serializers.PrimaryKeyRelatedField(
        queryset=Property.objects.all(), allow_null=True, required=False
    )
    required_skill = serializers.PrimaryKeyRelatedField(
        queryset=Skill.objects.all(), allow_null=True, required=False
    )
    service_zone = serializers.PrimaryKeyRelatedField(
        queryset=ServiceZone.objects.all(), allow_null=True, required=False
    )
    completion_contact = serializers.PrimaryKeyRelatedField(
        queryset=Contact.objects.all(), allow_null=True, required=False
    )

    client_name = serializers.CharField(source='account.name', read_only=True)
    worker_name = serializers.SerializerMethodField()
    worker_names = serializers.SerializerMethodField()
    assigned_workers = serializers.SerializerMethodField()
    
    # NEW: Property Location details for the Kanban Board
    property_address = serializers.CharField(source='property.address', read_only=True)
    property_unit = serializers.CharField(source='property.unit_number', read_only=True)
    
    # ALGORITHM FIELDS
    skill_name = serializers.CharField(source='required_skill.name', read_only=True)
    zone_name = serializers.CharField(source='service_zone.name', read_only=True)
    tasks = serializers.ListField(child=serializers.DictField(), write_only=True, required=False)
    worker_ids = serializers.ListField(
        child=serializers.IntegerField(min_value=1),
        write_only=True,
        required=False,
    )
    task_items = serializers.SerializerMethodField()
    open_issue_count = serializers.SerializerMethodField()
    latest_issue = serializers.SerializerMethodField()

    class Meta:
        model = Job
        fields = [
            'id', 'title', 'description', 'status', 'job_type', 'client_name',
            'account', 'organization', 'property', 'required_skill', 'service_zone',
            'worker_name', 'worker_names', 'assigned_workers', 'location_address',
            'property_address', 'property_unit', # Added to output
            'scheduled_start', 'estimated_duration_minutes', 'skill_name', 'minimum_proficiency',
            'zone_name', 'blocked_by', 'custom_data', 'completion_mode',
            'require_location', 'arrival_radius_meters', 'require_closeout_confirmation',
            'closeout_instruction', 'tasks', 'task_items', 'worker_ids', 'completion_contact',
            'completion_notification_method', 'completion_message_override',
            'open_issue_count', 'latest_issue'
        ]

    def get_open_issue_count(self, obj):
        return obj.issues.exclude(status='resolved').count()

    def get_latest_issue(self, obj):
        issue = obj.issues.exclude(status='resolved').select_related('worker__user').first()
        if not issue:
            return None
        return {
            'id': issue.id,
            'title': issue.title,
            'priority': issue.priority,
            'status': issue.status,
            'worker': issue.worker.user.get_full_name() or issue.worker.user.username,
            'created_at': issue.created_at,
        }

    def get_task_items(self, obj):
        return [
            {
                'id': task.id,
                'description': task.description,
                'requires_evidence': task.requires_evidence,
                'is_completed': task.is_completed,
                'assigned_worker_id': task.assigned_worker_id,
                'assigned_worker_name': (
                    task.assigned_worker.user.get_full_name() or task.assigned_worker.user.username
                    if task.assigned_worker else ''
                ),
            }
            for task in obj.tasks.select_related('assigned_worker__user')
        ]

    def _eligible_workers(self, worker_ids, workspace):
        workers = WorkerProfile.objects.filter(id__in=worker_ids, workspaces=workspace)
        if workspace.customer_account_id:
            workers = workers.filter(
                user__customer_accounts__account=workspace.customer_account,
                user__customer_accounts__can_work_jobs=True,
                user__customer_accounts__is_active=True,
            )
        return list(workers.select_related('user').distinct())

    def _save_tasks(self, job, tasks, worker_ids):
        for task in tasks:
            description = str(task.get('description', '')).strip()
            if description:
                assigned_worker_id = task.get('assigned_worker_id') or None
                try:
                    assigned_worker_id = int(assigned_worker_id) if assigned_worker_id else None
                except (TypeError, ValueError):
                    raise serializers.ValidationError({'tasks': 'Choose a valid task owner.'})
                if assigned_worker_id and assigned_worker_id not in worker_ids:
                    raise serializers.ValidationError({
                        'tasks': 'Every task owner must also be assigned to the job crew.',
                    })
                JobTask.objects.create(
                    job=job,
                    description=description[:255],
                    requires_evidence=bool(task.get('requires_evidence')),
                    assigned_worker_id=assigned_worker_id,
                )

    @transaction.atomic
    def create(self, validated_data):
        tasks = validated_data.pop('tasks', [])
        worker_ids = set(validated_data.pop('worker_ids', []))
        workspace = self.context['request'].active_organization
        workers = self._eligible_workers(worker_ids, workspace)
        if len(workers) != len(worker_ids):
            raise serializers.ValidationError({'worker_ids': 'Choose workers available to this workspace.'})
        if workers and validated_data.get('status', 'pending') == 'pending':
            validated_data['status'] = 'dispatched'
        job = super().create(validated_data)
        for index, worker in enumerate(workers):
            JobAssignment.objects.create(job=job, worker=worker, is_primary_worker=index == 0)
        self._save_tasks(job, tasks, worker_ids)
        return job

    @transaction.atomic
    def update(self, instance, validated_data):
        tasks = validated_data.pop('tasks', None)
        worker_ids = validated_data.pop('worker_ids', None)
        job = super().update(instance, validated_data)
        if worker_ids is not None:
            if job.status in {'in_progress', 'completed'}:
                raise serializers.ValidationError({'worker_ids': 'Crew cannot change after work starts.'})
            worker_ids = set(worker_ids)
            workers = self._eligible_workers(worker_ids, job.organization)
            if len(workers) != len(worker_ids):
                raise serializers.ValidationError({'worker_ids': 'Choose workers available to this workspace.'})
            job.worker_assignments.exclude(worker_id__in=worker_ids).delete()
            for worker in workers:
                JobAssignment.objects.get_or_create(job=job, worker=worker)
            primary = job.worker_assignments.order_by('-is_primary_worker', 'id').first()
            if primary and not primary.is_primary_worker:
                primary.is_primary_worker = True
                primary.save(update_fields=['is_primary_worker'])
            if workers and job.status == 'pending':
                job.status = 'dispatched'
                job.save(update_fields=['status'])
        if tasks is not None and job.status not in {'in_progress', 'completed'}:
            job.tasks.all().delete()
            assigned_ids = set(job.worker_assignments.values_list('worker_id', flat=True))
            self._save_tasks(job, tasks, assigned_ids)
        return job

    def get_worker_name(self, obj):
        assignment = (
            obj.worker_assignments.select_related('worker__user')
            .order_by('-is_primary_worker', 'id')
            .first()
        )
        if not assignment:
            return ''
        return assignment.worker.user.get_full_name() or assignment.worker.user.username

    def get_worker_names(self, obj):
        names = []
        assignments = obj.worker_assignments.select_related('worker__user').order_by(
            '-is_primary_worker', 'id'
        )
        for assignment in assignments:
            user = assignment.worker.user
            names.append(user.get_full_name() or user.username)
        return names

    def get_assigned_workers(self, obj):
        assigned_workers = []
        assignments = obj.worker_assignments.select_related('worker__user').order_by(
            '-is_primary_worker', 'id'
        )
        for assignment in assignments:
            user = assignment.worker.user
            assigned_workers.append({
                'id': assignment.worker_id,
                'assignment_id': assignment.id,
                'name': user.get_full_name() or user.username,
                'is_primary_worker': assignment.is_primary_worker,
            })
        return assigned_workers

    def validate(self, attrs):
        request = self.context.get('request')
        active_org = getattr(request, 'active_organization', None) if request else None

        if not active_org:
            raise serializers.ValidationError('Select an organization before working with jobs.')

        account = attrs.get('account') or getattr(self.instance, 'account', None)
        if account and account.organization_id != active_org.id:
            raise serializers.ValidationError({'account': 'Account must belong to the active organization.'})

        job_property = attrs.get('property') or getattr(self.instance, 'property', None)
        if job_property and job_property.account.organization_id != active_org.id:
            raise serializers.ValidationError({'property': 'Property must belong to the active organization.'})

        skill = attrs.get('required_skill') or getattr(self.instance, 'required_skill', None)
        skill_matches = not skill or (
            skill.customer_account_id == active_org.customer_account_id
            if active_org.customer_account_id else skill.workspace_id == active_org.id
        )
        if not skill_matches:
            raise serializers.ValidationError({'required_skill': 'Skill must belong to the active customer account.'})

        zone = attrs.get('service_zone') or getattr(self.instance, 'service_zone', None)
        if zone and zone.workspace_id != active_org.id:
            raise serializers.ValidationError({'service_zone': 'Service zone must belong to the active organization.'})

        completion_contact = attrs.get('completion_contact') or getattr(self.instance, 'completion_contact', None)
        if completion_contact and completion_contact.organization_id != active_org.id:
            raise serializers.ValidationError({'completion_contact': 'Completion contact must belong to the active organization.'})
        if completion_contact and account and completion_contact.account_id != account.id:
            raise serializers.ValidationError({'completion_contact': 'Completion contact must belong to the selected account.'})

        blocked_by = attrs.get('blocked_by') or getattr(self.instance, 'blocked_by', None)
        if blocked_by and blocked_by.organization_id != active_org.id:
            raise serializers.ValidationError({'blocked_by': 'Dependency job must belong to the active organization.'})
        if blocked_by and self.instance and blocked_by.id == self.instance.id:
            raise serializers.ValidationError({'blocked_by': 'A job cannot depend on itself.'})

        worker_ids = set(attrs.get('worker_ids') or [])
        if self.instance and 'worker_ids' not in attrs:
            worker_ids = set(self.instance.worker_assignments.values_list('worker_id', flat=True))
        for task in attrs.get('tasks') or []:
            assigned_worker_id = task.get('assigned_worker_id')
            try:
                assigned_worker_id = int(assigned_worker_id) if assigned_worker_id else None
            except (TypeError, ValueError):
                raise serializers.ValidationError({'tasks': 'Choose a valid task owner.'})
            if assigned_worker_id and assigned_worker_id not in worker_ids:
                raise serializers.ValidationError({
                    'tasks': 'Assign each task owner to the job crew first.',
                })

        return attrs

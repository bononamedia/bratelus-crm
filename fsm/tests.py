import json
from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from crm.models.contacts import Account, Contact, Property
from organizations.models import CustomerAccount, CustomerAccountMember, WorkerProfile, Workspace, WorkspaceMember

from .models import (
    CompletionNotificationDelivery, FieldEvent, FieldShift, Job, JobAssignment,
    JobIssue, JobTask, MaterialRun, WorkActivity,
)
from .tasks import send_completion_notifications
from .translation import translate_note_to_english


class FieldWorkflowTests(TestCase):
    def setUp(self):
        self.workspace = Workspace.objects.create(name='Field Company', slug='field-company')
        self.user = User.objects.create_user('field@example.com', password='StrongPass123!', first_name='Field')
        WorkspaceMember.objects.create(workspace=self.workspace, user=self.user, role='field_worker')
        self.worker = WorkerProfile.objects.create(user=self.user)
        self.worker.workspaces.add(self.workspace)
        self.account = Account.objects.create(organization=self.workspace, name='Customer')
        self.property = Property.objects.create(
            account=self.account,
            name='Service Site',
            address='100 Test Street',
            location_lat='26.122400',
            location_lng='-80.137300',
        )
        self.job = Job.objects.create(
            organization=self.workspace,
            account=self.account,
            property=self.property,
            title='Field Test',
            status='dispatched',
            completion_mode='tasks',
            arrival_radius_meters=250,
        )
        self.task = JobTask.objects.create(job=self.job, description='Complete service')
        self.assignment = JobAssignment.objects.create(job=self.job, worker=self.worker, is_primary_worker=True)
        self.client.force_login(self.user)
        self.location = {'latitude': 26.1224, 'longitude': -80.1373, 'accuracy': 8}

    def post_action(self, action, **extra):
        return self.client.post(
            reverse('api_field_job_action', args=[self.job.id]),
            data=json.dumps({**self.location, 'action': action, **extra}),
            content_type='application/json',
        )

    def start_shift(self):
        return self.client.post(
            reverse('api_field_shift'),
            data=json.dumps({**self.location, 'action': 'start'}),
            content_type='application/json',
        )

    def post_activity(self, action, **extra):
        return self.client.post(
            reverse('api_field_work_activity', args=[self.job.id]),
            data={**self.location, 'action': action, **extra},
        )

    def start_job(self):
        self.start_shift()
        self.post_action('accept')
        self.post_action('arrive')
        return self.post_action('start_work')

    def test_worker_must_follow_full_location_workflow(self):
        self.assertEqual(self.post_action('accept').status_code, 400)
        self.assertEqual(self.start_shift().status_code, 200)
        self.assertEqual(self.post_action('accept').status_code, 200)
        self.assertEqual(self.post_action('arrive').status_code, 200)
        self.assertEqual(self.post_action('start_work').status_code, 200)
        self.assertEqual(self.post_action('complete_task', task_id=self.task.id).status_code, 200)
        self.assertEqual(self.post_action('close_job', confirmed=False).status_code, 400)
        self.assertEqual(self.post_action('close_job', confirmed=True, note='Door locked').status_code, 200)

        self.job.refresh_from_db()
        self.assignment.refresh_from_db()
        self.task.refresh_from_db()
        self.assertEqual(self.job.status, 'completed')
        self.assertTrue(self.task.is_completed)
        self.assertIsNotNone(self.assignment.closeout_confirmed_at)
        self.assertEqual(FieldEvent.objects.filter(job=self.job, worker=self.worker).count(), 6)
        activity = WorkActivity.objects.get(worker=self.worker)
        self.assertEqual(activity.activity_type, 'onsite_work')
        self.assertIsNotNone(activity.ended_at)

    def test_material_run_tracks_travel_shopping_cost_and_resumes_work(self):
        self.assertEqual(self.start_job().status_code, 200)
        self.assertEqual(self.post_activity(
            'start_material_run', vendor_name='Home Depot',
            destination_address='200 Supply Road', shopping_list='Drywall and screws',
        ).status_code, 200)
        self.assertEqual(self.post_activity('arrive_vendor').status_code, 200)
        self.assertEqual(self.post_activity('leave_vendor').status_code, 200)
        self.assertEqual(self.post_activity('return_to_job', material_cost='84.25', mileage='12.4').status_code, 200)

        material_run = MaterialRun.objects.get(worker=self.worker)
        self.assertEqual(material_run.status, 'completed')
        self.assertEqual(str(material_run.material_cost), '84.25')
        self.assertEqual(str(material_run.mileage), '12.40')
        activities = WorkActivity.objects.filter(worker=self.worker).order_by('started_at', 'id')
        self.assertEqual(
            list(activities.values_list('activity_type', flat=True)),
            ['onsite_work', 'material_travel_out', 'material_shopping', 'material_travel_return', 'onsite_work'],
        )
        self.assertEqual(activities.filter(ended_at__isnull=True).count(), 1)
        self.assertEqual(activities.filter(ended_at__isnull=True).get().activity_type, 'onsite_work')

    def test_job_close_is_blocked_until_non_onsite_activity_is_finished(self):
        self.start_job()
        self.post_action('complete_task', task_id=self.task.id)
        self.assertEqual(self.post_activity('start_unpaid_break').status_code, 200)
        blocked = self.post_action('close_job', confirmed=True)
        self.assertEqual(blocked.status_code, 400)
        self.assertIn('Return to onsite work', blocked.json()['error'])
        self.assertEqual(self.post_activity('resume_onsite').status_code, 200)
        self.assertEqual(self.post_action('close_job', confirmed=True).status_code, 200)
        self.assertFalse(WorkActivity.objects.filter(worker=self.worker, ended_at__isnull=True).exists())

    def test_safari_field_pages_render_for_assigned_worker(self):
        dashboard = self.client.get(reverse('field_operations'))
        self.assertEqual(dashboard.status_code, 200)
        self.assertContains(dashboard, "Today's work")
        self.assertContains(dashboard, 'Enable location')
        job_page = self.client.get(reverse('field_job', args=[self.job.id]))
        self.assertEqual(job_page.status_code, 200)
        self.assertContains(job_page, 'Check in')
        self.assertContains(job_page, 'Report a problem')
        FieldShift.objects.create(
            worker=self.worker,
            workspace=self.workspace,
            start_lat=self.location['latitude'],
            start_lng=self.location['longitude'],
        )
        job_page = self.client.get(reverse('field_job', args=[self.job.id]))
        self.assertContains(job_page, 'Accept job')
        self.assertContains(job_page, 'Location')

    def test_arrival_is_rejected_outside_manager_radius(self):
        self.start_shift()
        self.post_action('accept')
        far_location = {'latitude': 27.0, 'longitude': -80.0, 'accuracy': 10, 'action': 'arrive'}
        response = self.client.post(
            reverse('api_field_job_action', args=[self.job.id]),
            data=json.dumps(far_location),
            content_type='application/json',
        )
        self.assertEqual(response.status_code, 400)
        self.assignment.refresh_from_db()
        self.assertIsNone(self.assignment.arrived_at)

    def test_worker_cannot_open_another_workers_job(self):
        other_user = User.objects.create_user('other@example.com', password='StrongPass123!')
        other_worker = WorkerProfile.objects.create(user=other_user)
        other_worker.workspaces.add(self.workspace)
        other_job = Job.objects.create(organization=self.workspace, account=self.account, title='Private assignment')
        JobAssignment.objects.create(job=other_job, worker=other_worker)
        response = self.client.get(reverse('field_job', args=[other_job.id]))
        self.assertEqual(response.status_code, 404)

    def test_worker_only_sees_and_completes_own_or_shared_tasks(self):
        other_user = User.objects.create_user('task-owner@example.com', password='StrongPass123!')
        other_worker = WorkerProfile.objects.create(user=other_user)
        other_worker.workspaces.add(self.workspace)
        JobAssignment.objects.create(job=self.job, worker=other_worker)
        self.task.assigned_worker = self.worker
        self.task.save(update_fields=['assigned_worker'])
        other_task = JobTask.objects.create(
            job=self.job,
            description='Other worker task',
            assigned_worker=other_worker,
        )
        shared_task = JobTask.objects.create(job=self.job, description='Shared crew task')

        page = self.client.get(reverse('field_job', args=[self.job.id]))
        self.assertContains(page, self.task.description)
        self.assertContains(page, shared_task.description)
        self.assertNotContains(page, other_task.description)
        self.assertEqual(
            self.post_action('complete_task', task_id=other_task.id).status_code,
            403,
        )

    def test_shift_requires_location(self):
        response = self.client.post(
            reverse('api_field_shift'),
            data=json.dumps({'action': 'start'}),
            content_type='application/json',
        )
        self.assertEqual(response.status_code, 400)
        self.assertFalse(FieldShift.objects.exists())

    def test_worker_can_report_location_linked_job_problem(self):
        self.start_shift()
        response = self.client.post(
            reverse('api_field_report_problem', args=[self.job.id]),
            data={
                **self.location,
                'title': 'Water leak near sink',
                'description': 'Stopped work and moved supplies away.',
                'voice_transcript': 'Hay agua debajo del fregadero.',
                'priority': 'safety',
            },
        )
        self.assertEqual(response.status_code, 201)
        issue = JobIssue.objects.get()
        self.assertEqual(issue.job, self.job)
        self.assertEqual(issue.job.account, self.account)
        self.assertEqual(issue.job.property, self.property)
        self.assertEqual(issue.worker, self.worker)
        self.assertEqual(issue.priority, 'safety')
        self.assertEqual(float(issue.lat), self.location['latitude'])
        self.assertTrue(FieldEvent.objects.filter(job=self.job, event_type='problem_reported').exists())

    def test_problem_report_requires_active_shift_and_location(self):
        url = reverse('api_field_report_problem', args=[self.job.id])
        no_shift = self.client.post(url, data={**self.location, 'title': 'Issue', 'description': 'Details'})
        self.assertEqual(no_shift.status_code, 400)
        self.start_shift()
        no_location = self.client.post(url, data={'title': 'Issue', 'description': 'Details'})
        self.assertEqual(no_location.status_code, 400)
        self.assertFalse(JobIssue.objects.exists())

    @patch.dict('os.environ', {}, clear=True)
    def test_spanish_note_is_preserved_when_translation_provider_is_pending(self):
        translated, language, status = translate_note_to_english('La puerta esta cerrada')
        self.assertEqual(translated, '')
        self.assertEqual(language, 'es')
        self.assertEqual(status, 'pending')

    @patch.dict('os.environ', {}, clear=True)
    def test_completion_notifications_render_and_keep_failed_delivery_audit(self):
        contact = Contact.objects.create(
            organization=self.workspace,
            account=self.account,
            first_name='Maria',
            last_name='Customer',
            email='maria@example.com',
            mobile='+15555550100',
            is_primary=True,
        )
        self.job.completion_contact = contact
        self.job.completion_notification_method = 'both'
        self.job.save(update_fields=['completion_contact', 'completion_notification_method'])

        send_completion_notifications(self.job.id)

        deliveries = CompletionNotificationDelivery.objects.filter(job=self.job).order_by('channel')
        self.assertEqual(deliveries.count(), 2)
        self.assertTrue(all(delivery.status == 'failed' for delivery in deliveries))
        self.assertTrue(all('Dear Maria' in delivery.message for delivery in deliveries))
        self.assertTrue(all('Field Test' in delivery.message for delivery in deliveries))


class MultiWorkspaceCalendarTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user('calendar-owner@example.com', password='StrongPass123!')
        self.customer_account = CustomerAccount.objects.create(name='Calendar Company', owner=self.owner)
        CustomerAccountMember.objects.create(account=self.customer_account, user=self.owner, role='owner', can_work_jobs=True)
        self.one = Workspace.objects.create(name='Blue Brand', slug='blue-brand', customer_account=self.customer_account, created_by=self.owner)
        self.two = Workspace.objects.create(name='Green Brand', slug='green-brand', customer_account=self.customer_account, created_by=self.owner)
        for workspace in (self.one, self.two):
            WorkspaceMember.objects.create(workspace=workspace, user=self.owner, role='admin')
        self.worker = WorkerProfile.objects.create(user=self.owner)
        self.worker.workspaces.add(self.one, self.two)
        self.account_one = Account.objects.create(organization=self.one, name='Blue Customer')
        self.account_two = Account.objects.create(organization=self.two, name='Green Customer')
        self.client.force_login(self.owner)

    def test_calendar_combines_authorized_workspace_events(self):
        now = timezone.now().replace(minute=0, second=0, microsecond=0)
        Job.objects.create(organization=self.one, account=self.account_one, title='Blue Job', scheduled_start=now)
        Job.objects.create(organization=self.two, account=self.account_two, title='Green Job', scheduled_start=now + timedelta(hours=2))
        response = self.client.get(reverse('api_calendar_jobs'), {
            'start': (now - timedelta(days=1)).isoformat(),
            'end': (now + timedelta(days=1)).isoformat(),
            'workspaces': f'{self.one.id},{self.two.id}',
        })
        self.assertEqual(response.status_code, 200)
        self.assertEqual({event['title'] for event in response.json()}, {'Blue Job', 'Green Job'})

    def test_board_and_calendar_render_the_same_job_form_sections(self):
        session = self.client.session
        session['active_org_id'] = str(self.one.id)
        session.save()

        board = self.client.get(reverse('jobs'))
        calendar = self.client.get(reverse('job_calendar'))

        self.assertEqual(board.status_code, 200)
        self.assertEqual(calendar.status_code, 200)
        for label in (
            'Job details',
            'Customer and location',
            'Assign crew',
            'Completion and task ownership',
            'Customer notification',
        ):
            self.assertContains(board, label)
            self.assertContains(calendar, label)
        self.assertContains(board, 'id="job-start"')
        self.assertContains(calendar, 'id="calendar-start"')

    def test_live_fleet_is_a_separate_map_only_view(self):
        session = self.client.session
        session['active_org_id'] = str(self.one.id)
        session.save()

        response = self.client.get(reverse('live_fleet'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Live Fleet')
        self.assertContains(response, reverse('api_live_fleet'))
        self.assertNotContains(response, 'Crew Assignment')

    def test_calendar_slot_creates_and_assigns_job(self):
        response = self.client.post(
            reverse('api_calendar_jobs'),
            data=json.dumps({
                'workspace_id': str(self.two.id),
                'title': 'Calendar Cleaning',
                'scheduled_start': timezone.now().isoformat(),
                'duration_minutes': 90,
                'account_id': self.account_two.id,
                'worker_ids': [self.worker.id],
                'completion_mode': 'tasks',
                'arrival_radius_meters': 175,
                'tasks': [{
                    'description': 'Clean bathrooms',
                    'assigned_worker_id': self.worker.id,
                    'requires_evidence': True,
                }],
            }),
            content_type='application/json',
        )
        self.assertEqual(response.status_code, 201)
        job = Job.objects.get(title='Calendar Cleaning')
        self.assertEqual(job.organization, self.two)
        self.assertEqual(job.estimated_duration_minutes, 90)
        self.assertEqual(job.arrival_radius_meters, 175)
        self.assertTrue(job.worker_assignments.filter(worker=self.worker).exists())
        self.assertTrue(job.tasks.filter(
            description='Clean bathrooms',
            assigned_worker=self.worker,
            requires_evidence=True,
        ).exists())

    def test_job_cancel_preserves_audit_and_assigned_job_cannot_be_deleted(self):
        session = self.client.session
        session['active_org_id'] = str(self.one.id)
        session.save()
        job = Job.objects.create(
            organization=self.one,
            account=self.account_one,
            title='Customer cancellation',
            status='dispatched',
        )
        JobAssignment.objects.create(job=job, worker=self.worker)

        delete_response = self.client.delete(reverse('api-job-detail', args=[job.id]))
        self.assertEqual(delete_response.status_code, 400)
        cancel_response = self.client.post(
            reverse('api-job-cancel', args=[job.id]),
            data=json.dumps({'reason': 'Customer requested another date'}),
            content_type='application/json',
        )
        self.assertEqual(cancel_response.status_code, 200)
        job.refresh_from_db()
        self.assertEqual(job.status, 'canceled')
        self.assertEqual(job.custom_data['cancellation']['reason'], 'Customer requested another date')

        archive_response = self.client.post(reverse('api-job-archive', args=[job.id]))
        self.assertEqual(archive_response.status_code, 200)
        job.refresh_from_db()
        self.assertIsNotNone(job.archived_at)
        self.assertEqual(job.archived_by, self.owner)
        self.assertFalse(self.client.get(reverse('api-job-list')).json())

        archived_response = self.client.get(reverse('api-job-archived'))
        self.assertEqual(archived_response.status_code, 200)
        self.assertEqual(archived_response.json()[0]['id'], job.id)

        restore_response = self.client.post(reverse('api-job-restore', args=[job.id]))
        self.assertEqual(restore_response.status_code, 200)
        job.refresh_from_db()
        self.assertIsNone(job.archived_at)

    def test_solo_mode_auto_assigns_owner_and_records_reschedule_history(self):
        session = self.client.session
        session['active_org_id'] = str(self.one.id)
        session.save()
        self.customer_account.operating_mode = 'solo'
        self.customer_account.save(update_fields=['operating_mode'])

        create_response = self.client.post(
            reverse('api-job-list'),
            data=json.dumps({
                'title': 'Owner route',
                'account': self.account_one.id,
                'scheduled_start': timezone.now().isoformat(),
            }),
            content_type='application/json',
        )
        self.assertEqual(create_response.status_code, 201)
        job = Job.objects.get(id=create_response.json()['id'])
        self.assertEqual(job.status, 'dispatched')
        self.assertTrue(job.worker_assignments.filter(worker=self.worker).exists())

        new_start = timezone.now() + timedelta(days=2)
        update_response = self.client.patch(
            reverse('api-job-detail', args=[job.id]),
            data=json.dumps({'scheduled_start': new_start.isoformat()}),
            content_type='application/json',
        )
        self.assertEqual(update_response.status_code, 200)
        job.refresh_from_db()
        self.assertEqual(len(job.custom_data['schedule_history']), 1)
        self.assertEqual(job.custom_data['schedule_history'][0]['changed_by_id'], self.owner.id)

    def test_unassigned_pending_draft_can_be_discarded(self):
        session = self.client.session
        session['active_org_id'] = str(self.one.id)
        session.save()
        draft = Job.objects.create(
            organization=self.one,
            account=self.account_one,
            title='Mistake draft',
        )
        response = self.client.delete(reverse('api-job-detail', args=[draft.id]))
        self.assertEqual(response.status_code, 204)
        self.assertFalse(Job.objects.filter(id=draft.id).exists())

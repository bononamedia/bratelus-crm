import json
from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from crm.models.contacts import Account, Contact, Property
from organizations.models import WorkerProfile, Workspace, WorkspaceMember

from .models import CompletionNotificationDelivery, FieldEvent, FieldShift, Job, JobAssignment, JobTask
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

    def test_safari_field_pages_render_for_assigned_worker(self):
        dashboard = self.client.get(reverse('field_operations'))
        self.assertEqual(dashboard.status_code, 200)
        self.assertContains(dashboard, "Today's work")
        self.assertContains(dashboard, 'Enable location')
        job_page = self.client.get(reverse('field_job', args=[self.job.id]))
        self.assertEqual(job_page.status_code, 200)
        self.assertContains(job_page, 'Check in')
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

    def test_shift_requires_location(self):
        response = self.client.post(
            reverse('api_field_shift'),
            data=json.dumps({'action': 'start'}),
            content_type='application/json',
        )
        self.assertEqual(response.status_code, 400)
        self.assertFalse(FieldShift.objects.exists())

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

from datetime import timedelta

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from fsm.models import WorkActivity
from organizations.models import (
    CustomerAccount, CustomerAccountMember, WorkerProfile, Workspace, WorkspaceMember,
)


class WorkActivityLedgerTests(TestCase):
    def setUp(self):
        self.manager = User.objects.create_user('manager@example.com', password='StrongPass123!')
        self.account = CustomerAccount.objects.create(name='Multi Brand', owner=self.manager)
        CustomerAccountMember.objects.create(account=self.account, user=self.manager, role='manager')
        self.blue = Workspace.objects.create(name='Blue Brand', slug='ledger-blue', customer_account=self.account)
        self.green = Workspace.objects.create(name='Green Brand', slug='ledger-green', customer_account=self.account)
        for workspace in (self.blue, self.green):
            WorkspaceMember.objects.create(workspace=workspace, user=self.manager, role='manager')
        worker_user = User.objects.create_user('worker@example.com', password='StrongPass123!', first_name='Taylor')
        self.worker = WorkerProfile.objects.create(user=worker_user)
        self.worker.workspaces.add(self.blue, self.green)
        now = timezone.now()
        WorkActivity.objects.create(
            workspace=self.blue, worker=self.worker, activity_type='onsite_work', is_paid=True,
            started_at=now - timedelta(hours=3), ended_at=now - timedelta(hours=1),
            start_lat=26, start_lng=-80,
        )
        WorkActivity.objects.create(
            workspace=self.green, worker=self.worker, activity_type='unpaid_break', is_paid=False,
            started_at=now - timedelta(minutes=30), ended_at=now - timedelta(minutes=15),
            start_lat=26, start_lng=-80,
        )
        self.client.force_login(self.manager)
        session = self.client.session
        session['active_org_id'] = str(self.blue.id)
        session.save()

    def test_ledger_combines_account_workspaces_and_filters_one_workspace(self):
        response = self.client.get(reverse('work_activity_ledger'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Blue Brand')
        self.assertContains(response, 'Green Brand')
        self.assertContains(response, '2.00')

        filtered = self.client.get(reverse('work_activity_ledger'), {'workspace': str(self.green.id)})
        self.assertEqual(filtered.status_code, 200)
        self.assertEqual(len(filtered.context['ledger']['rows']), 1)
        self.assertEqual(filtered.context['ledger']['rows'][0]['activity'].workspace, self.green)
        self.assertEqual(str(filtered.context['ledger']['unpaid_hours']), '0.25')

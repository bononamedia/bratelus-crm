from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from finance.models import SeatPricingTier, SubscriptionPlan, WorkspaceSubscription
from organizations.models import Workspace, WorkspaceMember


class WorkspaceOnboardingTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        plan = SubscriptionPlan.objects.create(name='Full CRM', code='onboarding-plan', base_monthly_amount=49)
        SeatPricingTier.objects.create(plan=plan, first_seat=1, up_to_seat=5, unit_amount=25)

    def test_signup_creates_owner_workspace_and_subscription(self):
        response = self.client.post(reverse('signup'), {
            'company_name': 'New Service Co',
            'first_name': 'New',
            'last_name': 'Owner',
            'email': 'owner@example.com',
            'password': 'VeryStrongPass123!',
        })
        self.assertRedirects(response, reverse('billing_overview'))
        user = User.objects.get(email='owner@example.com')
        workspace = Workspace.objects.get(created_by=user)
        self.assertTrue(WorkspaceMember.objects.filter(workspace=workspace, user=user, role='admin').exists())
        self.assertTrue(WorkspaceSubscription.objects.filter(workspace=workspace, seat_count=1).exists())

    def test_authenticated_user_can_create_another_workspace(self):
        user = User.objects.create_user('existing@example.com', password='VeryStrongPass123!')
        self.client.force_login(user)
        response = self.client.post(reverse('workspace_create'), {
            'name': 'Second Brand', 'billing_email': 'billing@example.com'
        })
        self.assertRedirects(response, reverse('admin_console'))
        self.assertTrue(WorkspaceMember.objects.filter(user=user, workspace__name='Second Brand', role='admin').exists())

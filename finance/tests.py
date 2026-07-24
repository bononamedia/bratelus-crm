from decimal import Decimal

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from crm.models.contacts import Account
from finance.models import Estimate, Invoice, PaymentReceived, SeatPricingTier, SubscriptionPlan
from finance.pricing import monthly_price
from fsm.models import Job
from organizations.models import Workspace, WorkspaceMember


class GraduatedPricingTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.plan = SubscriptionPlan.objects.create(
            name='Full CRM', code='test-full-crm', base_monthly_amount=49, included_users=1
        )
        for first, up_to, amount in [(1, 5, 25), (6, 10, 20), (11, 50, 15), (51, None, 10)]:
            SeatPricingTier.objects.create(
                plan=cls.plan, first_seat=first, up_to_seat=up_to, unit_amount=amount, sort_order=first
            )

    def test_base_price_includes_one_user(self):
        self.assertEqual(monthly_price(self.plan, 1), Decimal('49.00'))

    def test_price_is_graduated_without_tier_cliffs(self):
        self.assertEqual(monthly_price(self.plan, 6), Decimal('174.00'))
        self.assertEqual(monthly_price(self.plan, 11), Decimal('274.00'))
        self.assertEqual(monthly_price(self.plan, 51), Decimal('874.00'))
        self.assertEqual(monthly_price(self.plan, 52), Decimal('884.00'))


class WorkspaceFinanceWorkflowTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('books@example.com', password='StrongPass123!')
        self.workspace = Workspace.objects.create(name='Books Brand', slug='books-brand')
        WorkspaceMember.objects.create(workspace=self.workspace, user=self.user, role='admin')
        self.account = Account.objects.create(organization=self.workspace, name='Customer One')
        self.job = Job.objects.create(organization=self.workspace, account=self.account, title='Renovation')
        self.client.force_login(self.user)
        session = self.client.session
        session['active_org_id'] = str(self.workspace.id)
        session.save()

    def test_estimate_converts_to_job_linked_invoice(self):
        response = self.client.post(reverse('finance_sales'), {
            'action': 'create_estimate',
            'return_tab': 'estimates',
            'account_id': self.account.id,
            'job_id': self.job.id,
            'description': 'Project milestone',
            'quantity': '2',
            'unit_price': '125.00',
            'tax_amount': '10.00',
            'issue_date': timezone.localdate().isoformat(),
        })
        self.assertEqual(response.status_code, 302)
        estimate = Estimate.objects.get()
        self.assertEqual(estimate.total_amount, Decimal('260.00'))
        self.assertEqual(estimate.job, self.job)

        response = self.client.post(reverse('finance_estimate_convert', args=[estimate.id]))
        self.assertEqual(response.status_code, 302)
        estimate.refresh_from_db()
        invoice = estimate.converted_invoice
        self.assertEqual(invoice.job, self.job)
        self.assertEqual(invoice.line_items.get().total_price, Decimal('250.00'))

    def test_payment_updates_invoice_balance_and_status(self):
        invoice = Invoice.objects.create(
            organization=self.workspace,
            account=self.account,
            job=self.job,
            invoice_number='INV-TEST-1',
            due_date=timezone.localdate(),
            subtotal=Decimal('100.00'),
            total_amount=Decimal('100.00'),
        )
        response = self.client.post(reverse('finance_sales'), {
            'action': 'record_payment',
            'return_tab': 'payments',
            'account_id': self.account.id,
            'invoice_id': invoice.id,
            'amount': '100.00',
            'method': 'check',
            'payment_date': timezone.localdate().isoformat(),
        })
        self.assertEqual(response.status_code, 302)
        invoice.refresh_from_db()
        self.assertEqual(invoice.status, 'paid')
        self.assertEqual(invoice.balance_due, Decimal('0.00'))
        payment = PaymentReceived.objects.get()
        self.assertEqual(payment.invoice, invoice)
        self.assertEqual(payment.job, self.job)

    def test_unapplied_payment_can_be_linked_directly_to_job(self):
        response = self.client.post(reverse('finance_sales'), {
            'action': 'record_payment',
            'return_tab': 'payments',
            'account_id': self.account.id,
            'job_id': self.job.id,
            'amount': '75.00',
            'method': 'zelle',
            'payment_date': timezone.localdate().isoformat(),
        })
        self.assertEqual(response.status_code, 302)
        payment = PaymentReceived.objects.get()
        self.assertIsNone(payment.invoice)
        self.assertEqual(payment.job, self.job)

    def test_job_costing_and_payment_setup_pages_render(self):
        self.assertEqual(self.client.get(reverse('finance_job_costing')).status_code, 200)
        self.assertEqual(self.client.get(reverse('finance_payment_settings')).status_code, 200)

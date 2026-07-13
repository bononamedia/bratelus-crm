from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from crm.management.commands.import_zoho_contacts import fit_contact_field
from crm.models.contacts import Contact
from organizations.models import Workspace, WorkspaceMember


class AccountlessContactApiTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('admin@example.com', password='StrongPass123!')
        self.workspace = Workspace.objects.create(name='Test Brand', slug='test-brand', created_by=self.user)
        WorkspaceMember.objects.create(workspace=self.workspace, user=self.user, role='admin')
        self.client.force_login(self.user)

    def test_contact_can_be_created_without_account(self):
        response = self.client.post(reverse('api-contact-list'), {
            'account': None,
            'first_name': 'No',
            'last_name': 'Account',
            'email': '',
            'phone': '5551234567',
            'status': 'Imported',
        }, content_type='application/json')
        self.assertEqual(response.status_code, 201, response.content)
        contact = Contact.objects.get()
        self.assertEqual(contact.organization, self.workspace)
        self.assertIsNone(contact.account)

    def test_contacts_are_scoped_to_active_workspace(self):
        other = Workspace.objects.create(name='Other', slug='other')
        Contact.objects.create(organization=other, first_name='Hidden', last_name='Contact')
        response = self.client.get(reverse('api-contact-list'))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), [])

    def test_zoho_import_values_are_bounded_by_the_destination_field(self):
        self.assertEqual(len(fit_contact_field('phone', '1' * 80)), 50)
        self.assertEqual(fit_contact_field('description', 'Unbounded notes'), 'Unbounded notes')

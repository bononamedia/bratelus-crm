from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from crm.management.commands.import_zoho_contacts import fit_contact_field
from crm.models.contacts import Account, Contact, Property
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
        self.assertEqual(response.json()['results'], [])

    def test_contacts_are_paginated_and_searchable_by_formatted_phone(self):
        for index in range(105):
            Contact.objects.create(
                organization=self.workspace,
                first_name=f'Person {index}',
                last_name='Searchable',
                email=f'person{index}@example.com',
            )
        target = Contact.objects.create(
            organization=self.workspace,
            first_name='Fabio',
            last_name='Phone',
            phone='(914) 424-1858',
        )

        response = self.client.get(reverse('api-contact-list'))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['count'], 106)
        self.assertEqual(len(response.json()['results']), 100)

        search = self.client.get(reverse('api-contact-list'), {'search': '9144241858'})
        self.assertEqual(search.json()['count'], 1)
        self.assertEqual(search.json()['results'][0]['id'], target.id)

        view_all = self.client.get(reverse('api-contact-list'), {'page_size': 'all'})
        self.assertEqual(len(view_all.json()['results']), 106)

    def test_contact_can_be_assigned_only_to_an_account_in_its_workspace(self):
        contact = Contact.objects.create(
            organization=self.workspace,
            first_name='Accountless',
            last_name='Contact',
        )
        local_account = Account.objects.create(organization=self.workspace, name='Local Account')
        other = Workspace.objects.create(name='Other', slug='other')
        foreign_account = Account.objects.create(organization=other, name='Foreign Account')

        assigned = self.client.patch(
            reverse('api-contact-detail', args=[contact.id]),
            {'account': local_account.id},
            content_type='application/json',
        )
        self.assertEqual(assigned.status_code, 200, assigned.content)
        contact.refresh_from_db()
        self.assertEqual(contact.account, local_account)

        rejected = self.client.patch(
            reverse('api-contact-detail', args=[contact.id]),
            {'account': foreign_account.id},
            content_type='application/json',
        )
        self.assertEqual(rejected.status_code, 400)

    def test_contact_details_can_be_edited_without_changing_tenant_identity(self):
        contact = Contact.objects.create(
            organization=self.workspace,
            first_name='Cheryl',
            last_name='#NAME?',
            phone='2099184395',
            external_source='zoho',
            external_id='zoho-123',
        )
        response = self.client.patch(
            reverse('api-contact-detail', args=[contact.id]),
            {
                'last_name': 'Johnson',
                'email': 'cheryl@example.com',
                'phone': '209-918-4395',
                'mailing_country': 'United States',
                'status': 'Active',
                'description': 'Corrected by the workspace administrator.',
                'is_primary': True,
            },
            content_type='application/json',
        )
        self.assertEqual(response.status_code, 200, response.content)
        contact.refresh_from_db()
        self.assertEqual(contact.last_name, 'Johnson')
        self.assertEqual(contact.email, 'cheryl@example.com')
        self.assertTrue(contact.is_primary)
        self.assertEqual(contact.organization, self.workspace)
        self.assertEqual(contact.external_id, 'zoho-123')

    def test_contact_edit_panel_stacks_above_the_detail_panel(self):
        response = self.client.get(reverse('contacts'))
        self.assertContains(response, 'id="record-overlay" class="fixed inset-0 z-[75]')
        self.assertContains(response, 'id="record-panel" class="fixed inset-y-0 right-0 z-[80]')
        self.assertContains(response, 'id="detail-panel" class="fixed inset-y-0 right-0 z-50')
        self.assertContains(response, "icon: 'notebook-pen'")
        self.assertContains(response, "icon: 'calendar-clock'")
        self.assertContains(response, 'window.lucide.createIcons()')

    def test_accountless_contacts_can_be_organized_in_one_confirmed_action(self):
        with_address = Contact.objects.create(
            organization=self.workspace,
            first_name='Happy Creek Construction',
            last_name='Mr. Jordan',
            email='office@example.com',
            phone='8043472600',
            mailing_street='415 Adamson St',
            mailing_city='Richmond',
            mailing_state='VA',
            mailing_postal_code='23223',
            mailing_country='United States',
        )
        without_address = Contact.objects.create(
            organization=self.workspace,
            first_name='Fabio',
            last_name='Raimundo',
        )
        existing_account = Account.objects.create(organization=self.workspace, name='Existing')
        existing_contact = Contact.objects.create(
            organization=self.workspace,
            account=existing_account,
            first_name='Already',
            last_name='Organized',
        )
        url = reverse('api-contact-create-missing-accounts')

        preview = self.client.get(url)
        self.assertEqual(preview.status_code, 200)
        self.assertEqual(preview.json(), {
            'contacts': 2,
            'accounts': 2,
            'properties': 1,
            'without_address': 1,
        })

        unconfirmed = self.client.post(url, {}, content_type='application/json')
        self.assertEqual(unconfirmed.status_code, 400)

        created = self.client.post(url, {'confirm': True}, content_type='application/json')
        self.assertEqual(created.status_code, 201, created.content)
        self.assertEqual(created.json()['accounts'], 2)
        self.assertEqual(created.json()['properties'], 1)

        with_address.refresh_from_db()
        without_address.refresh_from_db()
        existing_contact.refresh_from_db()
        self.assertEqual(with_address.account.name, 'Happy Creek Construction')
        self.assertEqual(with_address.account.billing_city, 'Richmond')
        self.assertEqual(without_address.account.name, 'Fabio')
        self.assertEqual(existing_contact.account, existing_account)
        property_record = Property.objects.get(account=with_address.account)
        self.assertEqual(property_record.name, 'Happy Creek Construction')
        self.assertEqual(property_record.address, '415 Adamson St, Richmond, VA, 23223, United States')

        repeated = self.client.post(url, {'confirm': True}, content_type='application/json')
        self.assertEqual(repeated.status_code, 201)
        self.assertEqual(repeated.json()['accounts'], 0)

    def test_global_search_is_platform_admin_only_and_identifies_workspace(self):
        other = Workspace.objects.create(name='Other Brand', slug='other-brand')
        target = Contact.objects.create(
            organization=other,
            first_name='Global',
            last_name='Match',
            email='fabio@suntechsol.net',
        )
        url = reverse('api-contact-global-search')

        denied = self.client.get(url, {'search': 'fabio@suntechsol.net'})
        self.assertEqual(denied.status_code, 403)

        platform_admin = User.objects.create_superuser('root@example.com', password='StrongPass123!')
        WorkspaceMember.objects.create(workspace=self.workspace, user=platform_admin, role='admin')
        self.client.force_login(platform_admin)
        response = self.client.get(url, {'search': 'fabio@suntechsol.net'})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['count'], 1)
        self.assertEqual(response.json()['results'][0]['id'], target.id)
        self.assertEqual(response.json()['results'][0]['workspace_name'], 'Other Brand')

    def test_zoho_import_values_are_bounded_by_the_destination_field(self):
        self.assertEqual(len(fit_contact_field('phone', '1' * 80)), 50)
        self.assertEqual(fit_contact_field('description', 'Unbounded notes'), 'Unbounded notes')

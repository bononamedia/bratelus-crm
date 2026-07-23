from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from crm.management.commands.import_zoho_contacts import fit_contact_field
from crm.models.contacts import Account, Contact, PaymentMethod, Property
from organizations.models import Workspace, WorkspaceMember
from fsm.models import Job


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

    def test_account_bundle_creates_linked_records_atomically(self):
        response = self.client.post(
            reverse('api-account-create-bundle'),
            {
                'account': {'name': 'Bundle Client', 'email': 'billing@example.com'},
                'contact': {
                    'first_name': 'Ana',
                    'last_name': 'Client',
                    'email': 'ana@example.com',
                },
                'property': {
                    'name': 'Main Property',
                    'address': '100 Main St, Richmond, VA',
                },
                'payment_method': {
                    'card_type': 'Visa',
                    'last_four': '4242',
                    'use_created_property': True,
                },
            },
            content_type='application/json',
        )
        self.assertEqual(response.status_code, 201, response.content)
        account = Account.objects.get(name='Bundle Client')
        self.assertEqual(account.organization, self.workspace)
        self.assertEqual(Contact.objects.get().account, account)
        property_record = Property.objects.get()
        self.assertEqual(property_record.account, account)
        payment = PaymentMethod.objects.get()
        self.assertEqual(payment.account, account)
        self.assertEqual(payment.assigned_property, property_record)

    def test_invalid_account_bundle_rolls_back_every_record(self):
        response = self.client.post(
            reverse('api-account-create-bundle'),
            {
                'account': {'name': 'Should Roll Back'},
                'contact': {'first_name': 'Missing last name'},
            },
            content_type='application/json',
        )
        self.assertEqual(response.status_code, 400)
        self.assertFalse(Account.objects.filter(name='Should Roll Back').exists())

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

    def test_contact_can_be_duplicated_to_an_accessible_workspace_once(self):
        target = Workspace.objects.create(name='Second Brand', slug='second-brand')
        WorkspaceMember.objects.create(workspace=target, user=self.user, role='manager')
        source = Contact.objects.create(
            organization=self.workspace,
            first_name='Shared',
            last_name='Customer',
            email='shared@example.com',
            external_source='zoho',
            external_id='zcrm-shared-1',
            custom_data={'zoho_fields': {'Workspace': 'Second Brand'}},
        )
        url = reverse('api-contact-duplicate-to-workspace', args=[source.id])

        created = self.client.post(
            url,
            {'workspace_id': str(target.id)},
            content_type='application/json',
        )
        self.assertEqual(created.status_code, 201, created.content)
        self.assertTrue(created.json()['created'])
        copy = Contact.objects.get(organization=target)
        self.assertEqual(copy.email, source.email)
        self.assertIsNone(copy.account)
        self.assertEqual(copy.custom_data['duplication']['source_contact_id'], source.id)

        repeated = self.client.post(
            url,
            {'workspace_id': str(target.id)},
            content_type='application/json',
        )
        self.assertEqual(repeated.status_code, 200)
        self.assertFalse(repeated.json()['created'])
        self.assertEqual(Contact.objects.filter(organization=target).count(), 1)

    def test_platform_owner_can_reconcile_zoho_workspace_metadata(self):
        elaine = Workspace.objects.create(name="Elaine's House Cleaning", slug='elaines-house-cleaning')
        extra = Workspace.objects.create(name='Extra Help Pros', slug='extra-help-pros')
        elite = Workspace.objects.create(name='Elite Maids VA', slug='elite-maids-va')
        labels = [
            ('Perfect Cleaning', self.workspace),
            ("Elaine's House Cleaning", elaine),
            ('Extra Help', extra),
            ('Extra Help Pros', extra),
            ('Elite Maids', elite),
            ('', None),
        ]
        self.workspace.name = 'Perfect Cleaning'
        self.workspace.save(update_fields=['name'])
        for index, (label, _) in enumerate(labels):
            Contact.objects.create(
                organization=self.workspace,
                first_name=f'Imported {index}',
                last_name='Contact',
                external_source='zoho',
                external_id=f'zcrm-{index}',
                custom_data={'zoho_fields': {'Workspace': label}},
            )
        url = reverse('api-contact-reconcile-workspaces')
        denied = self.client.get(url)
        self.assertEqual(denied.status_code, 403)

        owner = User.objects.create_superuser('platform-owner@example.com', password='StrongPass123!')
        self.client.force_login(owner)
        session = self.client.session
        session['active_org_id'] = str(self.workspace.id)
        session.save()

        preview = self.client.get(url)
        self.assertEqual(preview.status_code, 200, preview.content)
        self.assertEqual(preview.json()['to_duplicate'], 4)
        self.assertEqual(preview.json()['same_workspace'], 1)
        self.assertEqual(preview.json()['blank_workspace'], 1)
        self.assertEqual(preview.json()['unknown_workspace'], 0)

        created = self.client.post(url, {'confirm': True}, content_type='application/json')
        self.assertEqual(created.status_code, 201, created.content)
        self.assertEqual(created.json()['created'], 4)
        self.assertEqual(Contact.objects.filter(organization=elaine).count(), 1)
        self.assertEqual(Contact.objects.filter(organization=extra).count(), 2)
        self.assertEqual(Contact.objects.filter(organization=elite).count(), 1)

        repeated = self.client.post(url, {'confirm': True}, content_type='application/json')
        self.assertEqual(repeated.status_code, 201)
        self.assertEqual(repeated.json()['created'], 0)
        self.assertEqual(repeated.json()['already_existed'], 4)

    def test_account_bundle_can_be_copied_to_another_workspace_once(self):
        target = Workspace.objects.create(name='Target Brand', slug='target-brand')
        WorkspaceMember.objects.create(workspace=target, user=self.user, role='admin')
        session = self.client.session
        session['active_org_id'] = str(self.workspace.id)
        session.save()
        account = Account.objects.create(
            organization=self.workspace,
            name='Bundled Customer',
            email='customer@example.com',
            billing_city='Richmond',
        )
        Contact.objects.create(
            organization=self.workspace,
            account=account,
            first_name='Bundle',
            last_name='Contact',
            external_source='zoho',
            external_id='bundle-contact-1',
        )
        source_property = Property.objects.create(
            account=account,
            name='Main Home',
            address='10 Main St, Richmond, VA',
            location_lat='37.540000',
            location_lng='-77.430000',
        )
        PaymentMethod.objects.create(
            account=account,
            assigned_property=source_property,
            is_default=True,
            card_type='Visa',
            last_four='4242',
            expiration_date='12/2030',
            processor_token='must-not-cross-workspaces',
        )
        url = reverse('api-account-duplicate-to-workspace', args=[account.id])
        response = self.client.post(
            url,
            {'workspace_id': str(target.id)},
            content_type='application/json',
        )
        self.assertEqual(response.status_code, 201, response.content)
        self.assertEqual(response.json()['copied'], {
            'contacts': 1,
            'properties': 1,
            'payment_methods': 1,
        })
        copied = Account.objects.get(organization=target)
        self.assertEqual(copied.name, account.name)
        self.assertEqual(copied.contacts.count(), 1)
        self.assertEqual(copied.properties.count(), 1)
        copied_method = copied.payment_methods.get()
        self.assertEqual(copied_method.last_four, '4242')
        self.assertEqual(copied_method.processor_token, '')
        self.assertEqual(copied_method.assigned_property.account, copied)

        repeated = self.client.post(
            url,
            {'workspace_id': str(target.id)},
            content_type='application/json',
        )
        self.assertEqual(repeated.status_code, 200)
        self.assertFalse(repeated.json()['created'])
        self.assertEqual(Account.objects.filter(organization=target).count(), 1)

    def test_zoho_import_values_are_bounded_by_the_destination_field(self):
        self.assertEqual(len(fit_contact_field('phone', '1' * 80)), 50)
        self.assertEqual(fit_contact_field('description', 'Unbounded notes'), 'Unbounded notes')


class CrmArchiveTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user('archive-admin@example.com', password='StrongPass123!')
        self.manager = User.objects.create_user('archive-manager@example.com', password='StrongPass123!')
        self.workspace = Workspace.objects.create(name='Archive Brand', slug='archive-brand', created_by=self.admin)
        WorkspaceMember.objects.create(workspace=self.workspace, user=self.admin, role='admin')
        WorkspaceMember.objects.create(workspace=self.workspace, user=self.manager, role='manager')
        self.account = Account.objects.create(organization=self.workspace, name='Archive Me')
        self.contact = Contact.objects.create(
            organization=self.workspace, account=self.account, first_name='Casey', last_name='Customer',
        )
        self.property = Property.objects.create(account=self.account, name='Home', address='10 Main St')
        self.client.force_login(self.admin)
        session = self.client.session
        session['active_org_id'] = str(self.workspace.id)
        session.save()

    def test_account_is_archived_restored_and_permanently_deleted(self):
        response = self.client.delete(reverse('api-account-detail', args=[self.account.id]))
        self.assertEqual(response.status_code, 204)
        self.account.refresh_from_db()
        self.assertIsNotNone(self.account.archived_at)
        self.assertEqual(self.account.archived_by, self.admin)
        self.assertEqual(self.client.get(reverse('api-account-list')).json(), [])
        self.assertEqual(self.client.get(reverse('api-property-list')).json(), [])
        self.assertEqual(self.client.get(reverse('api-contact-list')).json()['count'], 0)

        archived = self.client.get(reverse('api-account-archived'))
        self.assertEqual(archived.status_code, 200)
        self.assertEqual(archived.json()[0]['id'], self.account.id)
        restored = self.client.post(reverse('api-account-restore', args=[self.account.id]))
        self.assertEqual(restored.status_code, 200)
        self.assertEqual(self.client.get(reverse('api-contact-list')).json()['count'], 1)

        self.client.delete(reverse('api-account-detail', args=[self.account.id]))
        purged = self.client.delete(reverse('api-account-purge', args=[self.account.id]))
        self.assertEqual(purged.status_code, 204)
        self.assertFalse(Account.objects.filter(id=self.account.id).exists())

    def test_manager_cannot_permanently_clean_archive(self):
        self.account.archived_at = timezone.now()
        self.account.save(update_fields=['archived_at'])
        self.client.force_login(self.manager)
        session = self.client.session
        session['active_org_id'] = str(self.workspace.id)
        session.save()
        response = self.client.delete(reverse('api-account-purge', args=[self.account.id]))
        self.assertEqual(response.status_code, 403)
        self.assertTrue(Account.objects.filter(id=self.account.id).exists())

    def test_account_with_job_history_cannot_be_purged(self):
        Job.objects.create(organization=self.workspace, account=self.account, property=self.property, title='Historic job')
        self.account.archived_at = timezone.now()
        self.account.save(update_fields=['archived_at'])
        response = self.client.delete(reverse('api-account-purge', args=[self.account.id]))
        self.assertEqual(response.status_code, 400)
        self.assertTrue(Account.objects.filter(id=self.account.id).exists())

    def test_contact_archive_is_used_by_contacts_and_leads(self):
        response = self.client.delete(reverse('api-contact-detail', args=[self.contact.id]))
        self.assertEqual(response.status_code, 204)
        self.assertEqual(self.client.get(reverse('api-contact-list')).json()['count'], 0)
        archived = self.client.get(reverse('api-contact-archived'), {'page_size': 'all'}).json()
        self.assertEqual(archived['results'][0]['id'], self.contact.id)
        self.client.post(reverse('api-contact-restore', args=[self.contact.id]))
        self.contact.refresh_from_db()
        self.assertIsNone(self.contact.archived_at)

    def test_website_is_normalized_and_zip_fills_city_state(self):
        response = self.client.post(reverse('api-account-list'), {
            'name': 'Easy Entry', 'website': 'www.Example.COM/',
        }, content_type='application/json')
        self.assertEqual(response.status_code, 201, response.content)
        self.assertEqual(response.json()['website'], 'https://example.com')
        lookup = self.client.get(reverse('postal_code_lookup'), {'postal_code': '33301'})
        self.assertEqual(lookup.status_code, 200)
        self.assertEqual(lookup.json()['state'], 'FL')
        self.assertTrue(lookup.json()['city'])

import json

from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse

from finance.models import SeatPricingTier, SubscriptionPlan, WorkspaceSubscription
from crm.models.contacts import Account
from fsm.models import Job, JobAssignment
from organizations.models import (
    CustomerAccount,
    CustomerAccountMember,
    EmployeeDocument,
    EmployeeDocumentRequirement,
    Skill,
    WorkerProfile,
    Workspace,
    WorkspaceMember,
)
from organizations.permissions import (
    user_can_export_data,
    user_can_manage_people,
    user_can_manage_setup,
    user_can_manage_workspace,
    user_can_view_billing,
)


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
        self.assertIsNotNone(workspace.customer_account)
        self.assertTrue(CustomerAccountMember.objects.filter(account=workspace.customer_account, user=user, role='owner').exists())
        self.assertTrue(WorkspaceMember.objects.filter(workspace=workspace, user=user, role='admin').exists())
        self.assertTrue(WorkspaceSubscription.objects.filter(workspace=workspace, seat_count=1).exists())


class AccountTeamTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user('account-owner@example.com', password='StrongPass123!')
        self.account = CustomerAccount.objects.create(name='Parent Company', owner=self.owner)
        CustomerAccountMember.objects.create(account=self.account, user=self.owner, role='owner', can_work_jobs=True)
        self.first = Workspace.objects.create(name='Brand One', slug='brand-one', customer_account=self.account, created_by=self.owner)
        self.second = Workspace.objects.create(name='Brand Two', slug='brand-two', customer_account=self.account, created_by=self.owner)
        for workspace in (self.first, self.second):
            WorkspaceMember.objects.create(workspace=workspace, user=self.owner, role='admin')
        self.employee = User.objects.create_user('team@example.com', password='StrongPass123!')
        self.member = CustomerAccountMember.objects.create(account=self.account, user=self.employee, role='employee')
        WorkspaceMember.objects.create(workspace=self.first, user=self.employee, role='employee')
        self.client.force_login(self.owner)

    def test_owner_assigns_office_user_as_field_capable_across_workspaces(self):
        response = self.client.post(reverse('workforce'), {
            'account_member_id': self.member.id,
            'role': 'employee',
            'can_work_jobs': 'yes',
            'workspace_ids': [str(self.first.id), str(self.second.id)],
        })
        self.assertRedirects(response, reverse('workforce'))
        self.member.refresh_from_db()
        self.assertTrue(self.member.can_work_jobs)
        self.assertEqual(WorkspaceMember.objects.filter(user=self.employee, is_active=True).count(), 2)
        self.assertEqual(WorkerProfile.objects.get(user=self.employee).workspaces.count(), 2)

    def test_owner_manages_account_wide_employee_profile_and_skills(self):
        skill = Skill.objects.create(customer_account=self.account, name='Floor Care')
        detail = self.client.get(reverse('team_member_detail', args=[self.member.id]))
        self.assertEqual(detail.status_code, 200)
        self.assertContains(detail, 'Employee Profile')
        response = self.client.post(reverse('team_member_detail', args=[self.member.id]), {
            'action': 'update_profile',
            'first_name': 'Team',
            'last_name': 'Member',
            'username': 'team-member',
            'email': 'team@example.com',
            'phone': '555-100-2000',
            'job_title': 'Lead Technician',
            'employment_type': 'w2',
            'photo_required': 'yes',
            'drivers_license_required': 'yes',
        })
        self.assertRedirects(response, reverse('team_member_detail', args=[self.member.id]))
        self.member.refresh_from_db()
        profile = WorkerProfile.objects.get(user=self.employee)
        self.assertEqual(profile.job_title, 'Lead Technician')
        self.employee.refresh_from_db()
        self.assertEqual(self.employee.username, 'team-member')
        self.assertTrue(self.member.photo_required)
        self.assertTrue(self.member.drivers_license_required)

        response = self.client.post(reverse('team_member_detail', args=[self.member.id]), {
            'action': 'update_skills',
            'skill_ids': [str(skill.id)],
            f'skill_level_{skill.id}': '3',
        })
        self.assertRedirects(response, reverse('team_member_detail', args=[self.member.id]))
        self.assertTrue(profile.skills.filter(skill=skill, proficiency_level=3).exists())

    def test_owner_can_unassign_worker_after_workspace_access_was_removed(self):
        worker = WorkerProfile.objects.create(user=self.employee)
        worker.workspaces.add(self.first)
        account = Account.objects.create(organization=self.first, name='Dispatch Customer')
        job = Job.objects.create(organization=self.first, account=account, title='Dispatch Job', status='dispatched')
        JobAssignment.objects.create(job=job, worker=worker, is_primary_worker=True)
        worker.workspaces.remove(self.first)
        session = self.client.session
        session['active_org_id'] = str(self.first.id)
        session.save()

        response = self.client.post(
            reverse('api-job-unassign-worker', args=[job.id]),
            data=json.dumps({'worker_id': worker.id}),
            content_type='application/json',
        )

        self.assertEqual(response.status_code, 200)
        self.assertFalse(JobAssignment.objects.filter(job=job, worker=worker).exists())
        job.refresh_from_db()
        self.assertEqual(job.status, 'pending')

    def test_owner_removes_employee_access_without_deleting_history(self):
        profile = WorkerProfile.objects.create(user=self.employee)
        profile.workspaces.add(self.first)

        response = self.client.post(reverse('team_member_detail', args=[self.member.id]), {
            'action': 'remove_employee',
        })

        self.assertRedirects(response, reverse('workforce'))
        self.member.refresh_from_db()
        self.employee.refresh_from_db()
        self.assertFalse(self.member.is_active)
        self.assertFalse(self.employee.is_active)
        self.assertTrue(WorkerProfile.objects.filter(id=profile.id).exists())
        self.assertFalse(WorkspaceMember.objects.get(workspace=self.first, user=self.employee).is_active)

    def test_employee_with_active_job_must_be_unassigned_before_removal(self):
        profile = WorkerProfile.objects.create(user=self.employee)
        profile.workspaces.add(self.first)
        account = Account.objects.create(organization=self.first, name='Active Customer')
        job = Job.objects.create(organization=self.first, account=account, title='Active Job', status='dispatched')
        JobAssignment.objects.create(job=job, worker=profile)

        response = self.client.post(reverse('team_member_detail', args=[self.member.id]), {
            'action': 'remove_employee',
        })

        self.assertRedirects(response, reverse('team_member_detail', args=[self.member.id]))
        self.member.refresh_from_db()
        self.assertTrue(self.member.is_active)
        self.assertTrue(JobAssignment.objects.filter(job=job, worker=profile).exists())

    def test_employee_uploads_requested_document(self):
        profile = WorkerProfile.objects.create(user=self.employee)
        profile.workspaces.add(self.first)
        requirement = EmployeeDocumentRequirement.objects.create(
            account=self.account,
            title="Driver's license",
            document_type='drivers_license',
        )
        requirement.requested_members.add(self.member)
        self.client.force_login(self.employee)
        response = self.client.post(reverse('employee_profile'), {
            'action': 'upload_document',
            'requirement_id': requirement.id,
            'document': SimpleUploadedFile('license.jpg', b'fake-image', content_type='image/jpeg'),
        })
        self.assertRedirects(response, reverse('employee_profile'))
        self.assertTrue(EmployeeDocument.objects.filter(
            account=self.account,
            user=self.employee,
            requirement=requirement,
            status='pending',
        ).exists())

    def test_required_photo_redirects_employee_to_onboarding(self):
        profile = WorkerProfile.objects.create(user=self.employee)
        profile.workspaces.add(self.first)
        self.member.photo_required = True
        self.member.save(update_fields=['photo_required'])
        self.client.force_login(self.employee)
        response = self.client.get(reverse('dashboard'))
        self.assertRedirects(response, reverse('employee_profile'))

    def test_authenticated_user_can_create_another_workspace(self):
        user = User.objects.create_user('existing@example.com', password='VeryStrongPass123!')
        existing = Workspace.objects.create(name='Existing Brand', slug='existing-brand', created_by=user)
        WorkspaceMember.objects.create(workspace=existing, user=user, role='admin')
        self.client.force_login(user)
        response = self.client.post(reverse('workspace_create'), {
            'name': 'Second Brand', 'billing_email': 'billing@example.com'
        })
        self.assertRedirects(response, reverse('admin_console'))
        self.assertTrue(WorkspaceMember.objects.filter(user=user, workspace__name='Second Brand', role='admin').exists())

    def test_non_admin_cannot_create_another_workspace(self):
        user = User.objects.create_user('employee@example.com', password='VeryStrongPass123!')
        workspace = Workspace.objects.create(name='Employer', slug='employer')
        WorkspaceMember.objects.create(workspace=workspace, user=user, role='employee')
        self.client.force_login(user)
        response = self.client.post(reverse('workspace_create'), {'name': 'Not Allowed'})
        self.assertEqual(response.status_code, 403)


class WorkspaceRoleTests(TestCase):
    def setUp(self):
        self.workspace = Workspace.objects.create(name='Role Brand', slug='role-brand')

    def member(self, role, billing=False):
        user = User.objects.create_user(f'{role}-{billing}@example.com', password='StrongPass123!')
        WorkspaceMember.objects.create(
            workspace=self.workspace,
            user=user,
            role=role,
            can_view_billing=billing,
        )
        return user

    def test_role_capabilities_are_separate(self):
        admin = self.member('admin')
        manager = self.member('manager')
        billing_manager = self.member('manager', billing=True)
        employee = self.member('employee')
        field_worker = self.member('field_worker')

        self.assertTrue(user_can_manage_setup(admin, self.workspace))
        self.assertTrue(user_can_export_data(admin, self.workspace))
        self.assertFalse(user_can_manage_setup(manager, self.workspace))
        self.assertTrue(user_can_manage_people(manager, self.workspace))
        self.assertFalse(user_can_export_data(manager, self.workspace))
        self.assertFalse(user_can_view_billing(manager, self.workspace))
        self.assertTrue(user_can_view_billing(billing_manager, self.workspace))
        self.assertTrue(user_can_manage_workspace(employee, self.workspace))
        self.assertFalse(user_can_manage_people(employee, self.workspace))
        self.assertFalse(user_can_manage_workspace(field_worker, self.workspace))

    def test_django_admin_is_superuser_only(self):
        staff = User.objects.create_user('staff@example.com', password='StrongPass123!', is_staff=True)
        self.client.force_login(staff)
        denied = self.client.get('/admin/')
        self.assertEqual(denied.status_code, 302)
        self.assertIn('/admin/login/', denied.url)

        owner = User.objects.create_superuser('owner@example.com', password='StrongPass123!')
        self.client.force_login(owner)
        allowed = self.client.get('/admin/')
        self.assertEqual(allowed.status_code, 200)

    def test_manager_cannot_promote_users_or_change_workspace_setup(self):
        manager = self.member('manager')
        self.client.force_login(manager)
        setup_change = self.client.post(reverse('admin_console'), {
            'action': 'create_custom_field',
            'label': 'Forbidden field',
        })
        self.assertEqual(setup_change.status_code, 403)
        promotion = self.client.post(reverse('admin_console'), {
            'action': 'invite_member',
            'email': 'promoted@example.com',
            'first_name': 'Promoted',
            'last_name': 'User',
            'role': 'admin',
            'confirm_price': 'yes',
        })
        self.assertEqual(promotion.status_code, 403)

    def test_manager_can_manage_skills_and_edit_employees(self):
        manager = self.member('manager')
        employee = self.member('employee')
        member = WorkspaceMember.objects.get(workspace=self.workspace, user=employee)
        profile = WorkerProfile.objects.create(user=employee)
        profile.workspaces.add(self.workspace)
        self.client.force_login(manager)

        skill_response = self.client.post(reverse('admin_console'), {
            'action': 'create_skill',
            'name': 'Floor Care',
            'description': 'Commercial floor service',
        })
        self.assertRedirects(skill_response, reverse('admin_console'))
        self.assertTrue(Skill.objects.filter(workspace=self.workspace, name='Floor Care').exists())

        edit_response = self.client.post(reverse('admin_console'), {
            'action': 'update_member_access',
            'member_id': member.id,
            'first_name': 'Edited',
            'last_name': 'Employee',
            'email': 'edited-employee@example.com',
            'phone': '555-222-3333',
            'employment_type': 'w2',
            'role': 'field_worker',
        })
        self.assertRedirects(edit_response, reverse('admin_console'))
        member.refresh_from_db()
        employee.refresh_from_db()
        profile.refresh_from_db()
        self.assertEqual(member.role, 'field_worker')
        self.assertEqual(employee.get_full_name(), 'Edited Employee')
        self.assertEqual(profile.phone, '555-222-3333')
        self.assertEqual(profile.employment_type, 'w2')

    def test_manager_cannot_edit_an_administrator(self):
        manager = self.member('manager')
        admin = self.member('admin')
        member = WorkspaceMember.objects.get(workspace=self.workspace, user=admin)
        self.client.force_login(manager)
        response = self.client.post(reverse('admin_console'), {
            'action': 'update_member_access',
            'member_id': member.id,
            'first_name': 'Not',
            'last_name': 'Allowed',
            'email': admin.email,
            'role': 'admin',
        })
        self.assertEqual(response.status_code, 403)

    def test_field_worker_can_update_only_their_profile(self):
        worker_user = self.member('field_worker')
        profile = WorkerProfile.objects.create(user=worker_user)
        profile.workspaces.add(self.workspace)
        self.client.force_login(worker_user)
        response = self.client.post(reverse('employee_profile'), {
            'first_name': 'Field',
            'last_name': 'Specialist',
            'phone': '555-123-4567',
            'employment_type': '1099',
            'home_street': '10 Main St',
            'home_city': 'Richmond',
            'home_state': 'VA',
            'home_postal_code': '23220',
            'home_country': 'United States',
            'emergency_contact_name': 'Emergency Person',
            'emergency_contact_phone': '555-999-0000',
        })
        self.assertRedirects(response, reverse('employee_profile'))
        profile.refresh_from_db()
        worker_user.refresh_from_db()
        self.assertEqual(worker_user.get_full_name(), 'Field Specialist')
        self.assertEqual(profile.employment_type, '1099')
        self.assertEqual(profile.home_city, 'Richmond')
        self.assertEqual(profile.emergency_contact_name, 'Emergency Person')

from django.contrib.auth.models import User
from asgiref.sync import async_to_sync
from channels.testing import WebsocketCommunicator
from django.test import TestCase, TransactionTestCase, override_settings
from django.urls import reverse

from crm.models.contacts import Account
from fsm.models import Job
from organizations.models import CustomerAccount, CustomerAccountMember, Workspace, WorkspaceMember

from .models import ChatConversation, ChatMessage, ChatParticipant
from .consumers import ChatConsumer


class InternalChatTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user('chat-owner@example.com', password='StrongPass123!', first_name='Avery')
        self.employee = User.objects.create_user('chat-worker@example.com', password='StrongPass123!', first_name='Taylor')
        self.outsider = User.objects.create_user('outsider@example.com', password='StrongPass123!')
        self.customer_account = CustomerAccount.objects.create(name='Chat Company', owner=self.owner)
        CustomerAccountMember.objects.create(account=self.customer_account, user=self.owner, role='owner')
        CustomerAccountMember.objects.create(account=self.customer_account, user=self.employee, role='employee')
        self.workspace = Workspace.objects.create(
            name='Chat Brand', slug='chat-brand', customer_account=self.customer_account, created_by=self.owner,
        )
        WorkspaceMember.objects.create(workspace=self.workspace, user=self.owner, role='admin')
        WorkspaceMember.objects.create(workspace=self.workspace, user=self.employee, role='employee')
        self.crm_account = Account.objects.create(organization=self.workspace, name='Job Customer')
        self.job = Job.objects.create(organization=self.workspace, account=self.crm_account, title='Site Visit')
        self.client.force_login(self.owner)
        session = self.client.session
        session['active_org_id'] = str(self.workspace.id)
        session.save()

    def test_owner_creates_account_wide_conversation_with_employee(self):
        response = self.client.post(reverse('chat_inbox'), {
            'title': 'Site coordination',
            'workspace_id': str(self.workspace.id),
            'participant_ids': [str(self.employee.id)],
        })
        conversation = ChatConversation.objects.get()
        self.assertRedirects(response, reverse('chat_conversation', args=[conversation.id]))
        self.assertEqual(conversation.account, self.customer_account)
        self.assertEqual(conversation.workspace, self.workspace)
        self.assertEqual(
            set(conversation.participants.values_list('user_id', flat=True)),
            {self.owner.id, self.employee.id},
        )
        self.assertTrue(conversation.messages.filter(message_type='system').exists())

    def test_owner_can_create_conversation_with_account_wide_context(self):
        response = self.client.post(reverse('chat_inbox'), {
            'title': 'All brands coordination',
            'workspace_id': '',
            'participant_ids': [str(self.employee.id)],
        })
        conversation = ChatConversation.objects.get()
        self.assertRedirects(response, reverse('chat_conversation', args=[conversation.id]))
        self.assertIsNone(conversation.workspace)

    def test_participant_sends_message_and_attaches_transcript_to_job(self):
        conversation = ChatConversation.objects.create(
            account=self.customer_account, workspace=self.workspace, title='Materials', created_by=self.owner,
        )
        ChatParticipant.objects.create(conversation=conversation, user=self.owner)
        ChatParticipant.objects.create(conversation=conversation, user=self.employee)
        response = self.client.post(reverse('chat_message', args=[conversation.id]), {'body': 'Please bring the receipt.'})
        self.assertEqual(response.status_code, 201)
        self.assertTrue(ChatMessage.objects.filter(conversation=conversation, body='Please bring the receipt.').exists())

        attach = self.client.post(reverse('chat_attach_job', args=[conversation.id]), {'job_id': self.job.id})
        self.assertRedirects(attach, reverse('chat_conversation', args=[conversation.id]))
        conversation.refresh_from_db()
        self.assertEqual(conversation.job, self.job)
        self.assertIsNotNone(conversation.transcript_attached_at)
        self.assertTrue(conversation.messages.filter(message_type='system', body__contains=f'job #{self.job.id}').exists())

    def test_nonparticipant_cannot_read_or_post_to_conversation(self):
        conversation = ChatConversation.objects.create(account=self.customer_account, title='Private', created_by=self.owner)
        ChatParticipant.objects.create(conversation=conversation, user=self.owner)
        self.client.force_login(self.employee)
        session = self.client.session
        session['active_org_id'] = str(self.workspace.id)
        session.save()
        self.assertEqual(self.client.get(reverse('chat_conversation', args=[conversation.id])).status_code, 404)
        self.assertEqual(self.client.post(reverse('chat_message', args=[conversation.id]), {'body': 'No access'}).status_code, 404)

    def test_user_outside_customer_account_cannot_open_chat(self):
        self.client.force_login(self.outsider)
        response = self.client.get(reverse('chat_inbox'))
        self.assertEqual(response.status_code, 403)


@override_settings(CHANNEL_LAYERS={'default': {'BACKEND': 'channels.layers.InMemoryChannelLayer'}})
class ChatWebSocketTests(TransactionTestCase):
    def setUp(self):
        self.user = User.objects.create_user('socket@example.com', password='StrongPass123!', first_name='Morgan')
        self.account = CustomerAccount.objects.create(name='Socket Company', owner=self.user)
        CustomerAccountMember.objects.create(account=self.account, user=self.user, role='owner')
        self.conversation = ChatConversation.objects.create(account=self.account, title='Live coordination', created_by=self.user)
        ChatParticipant.objects.create(conversation=self.conversation, user=self.user)

    def test_participant_receives_message_over_websocket(self):
        async def scenario():
            communicator = WebsocketCommunicator(ChatConsumer.as_asgi(), f'/ws/chat/{self.conversation.id}/')
            communicator.scope['user'] = self.user
            communicator.scope['url_route'] = {'args': (), 'kwargs': {'conversation_id': str(self.conversation.id)}}
            connected, _ = await communicator.connect()
            self.assertTrue(connected)
            await communicator.send_json_to({'body': 'Live message'})
            response = await communicator.receive_json_from()
            self.assertEqual(response['body'], 'Live message')
            self.assertEqual(response['sender_id'], self.user.id)
            await communicator.disconnect()

        async_to_sync(scenario)()
        self.assertTrue(ChatMessage.objects.filter(conversation=self.conversation, body='Live message').exists())

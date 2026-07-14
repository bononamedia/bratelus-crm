from django.contrib.auth.models import User
from asgiref.sync import async_to_sync
from channels.testing import WebsocketCommunicator
from django.test import TestCase, TransactionTestCase, override_settings
from django.urls import reverse
from unittest.mock import patch

from crm.models.contacts import Account
from fsm.models import Job
from organizations.models import CustomerAccount, CustomerAccountMember, Workspace, WorkspaceMember

from .models import ChatConversation, ChatMessage, ChatParticipant, WebPushSubscription
from .consumers import ChatConsumer
from .tasks import send_chat_push


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

    @patch('chat.views.send_chat_push.delay')
    def test_participant_sends_message_and_attaches_transcript_to_job(self, push_delay):
        conversation = ChatConversation.objects.create(
            account=self.customer_account, workspace=self.workspace, title='Materials', created_by=self.owner,
        )
        ChatParticipant.objects.create(conversation=conversation, user=self.owner)
        ChatParticipant.objects.create(conversation=conversation, user=self.employee)
        response = self.client.post(reverse('chat_message', args=[conversation.id]), {'body': 'Please bring the receipt.'})
        self.assertEqual(response.status_code, 201)
        self.assertTrue(ChatMessage.objects.filter(conversation=conversation, body='Please bring the receipt.').exists())
        push_delay.assert_called_once()

        owner_participant = ChatParticipant.objects.get(conversation=conversation, user=self.owner)
        employee_participant = ChatParticipant.objects.get(conversation=conversation, user=self.employee)
        self.assertEqual(owner_participant.unread_count, 0)
        self.assertEqual(employee_participant.unread_count, 1)

        self.client.force_login(self.employee)
        session = self.client.session
        session['active_org_id'] = str(self.workspace.id)
        session.save()
        self.client.get(reverse('chat_conversation', args=[conversation.id]))
        employee_participant.refresh_from_db()
        self.assertEqual(employee_participant.unread_count, 0)

        self.client.force_login(self.owner)
        session = self.client.session
        session['active_org_id'] = str(self.workspace.id)
        session.save()

        attach = self.client.post(reverse('chat_attach_job', args=[conversation.id]), {'job_id': self.job.id})
        self.assertRedirects(attach, reverse('chat_conversation', args=[conversation.id]))
        conversation.refresh_from_db()
        self.assertEqual(conversation.job, self.job)
        self.assertIsNotNone(conversation.transcript_attached_at)
        self.assertTrue(conversation.messages.filter(message_type='system', body__contains=f'job #{self.job.id}').exists())

    def test_user_can_register_and_remove_secure_push_subscription(self):
        payload = {
            'endpoint': 'https://push.example.test/device-1',
            'keys': {'p256dh': 'public-key', 'auth': 'auth-secret'},
        }
        response = self.client.post(
            reverse('chat_push_subscribe'), data=payload, content_type='application/json',
        )
        self.assertEqual(response.status_code, 200)
        subscription = WebPushSubscription.objects.get(endpoint=payload['endpoint'])
        self.assertEqual(subscription.user, self.owner)

        response = self.client.post(
            reverse('chat_push_unsubscribe'), data={'endpoint': payload['endpoint']},
            content_type='application/json',
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(WebPushSubscription.objects.exists())

    def test_push_subscription_rejects_insecure_endpoint(self):
        response = self.client.post(reverse('chat_push_subscribe'), data={
            'endpoint': 'http://push.example.test/device-1',
            'keys': {'p256dh': 'public-key', 'auth': 'auth-secret'},
        }, content_type='application/json')
        self.assertEqual(response.status_code, 400)

    @override_settings(
        CHAT_VAPID_PUBLIC_KEY='public-key', CHAT_VAPID_PRIVATE_KEY='private-key',
        CHAT_VAPID_SUBJECT='mailto:support@bratelus.com',
    )
    @patch('chat.tasks.webpush')
    def test_push_task_sends_to_other_participants(self, webpush_mock):
        conversation = ChatConversation.objects.create(
            account=self.customer_account, workspace=self.workspace, title='Push test', created_by=self.owner,
        )
        ChatParticipant.objects.create(conversation=conversation, user=self.owner)
        ChatParticipant.objects.create(conversation=conversation, user=self.employee)
        WebPushSubscription.objects.create(
            user=self.employee, endpoint='https://push.example.test/device-2', p256dh='public-key', auth='auth-secret',
        )
        message = ChatMessage.objects.create(
            conversation=conversation, sender=self.owner, sender_name='Avery', body='New assignment ready.',
        )

        result = send_chat_push(message.id)

        self.assertEqual(result, {'status': 'sent', 'count': 1})
        webpush_mock.assert_called_once()

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

    @patch('chat.consumers.send_chat_push.delay')
    def test_participant_receives_message_over_websocket(self, push_delay):
        async def scenario():
            communicator = WebsocketCommunicator(ChatConsumer.as_asgi(), f'/ws/chat/{self.conversation.id}/')
            communicator.scope['user'] = self.user
            communicator.scope['url_route'] = {'args': (), 'kwargs': {'conversation_id': str(self.conversation.id)}}
            connected, _ = await communicator.connect()
            self.assertTrue(connected)
            await communicator.send_json_to({'body': 'Live message'})
            response = await communicator.receive_json_from()
            while response.get('type') != 'message':
                response = await communicator.receive_json_from()
            self.assertEqual(response['body'], 'Live message')
            self.assertEqual(response['sender_id'], self.user.id)
            await communicator.disconnect()

        async_to_sync(scenario)()
        self.assertTrue(ChatMessage.objects.filter(conversation=self.conversation, body='Live message').exists())
        push_delay.assert_called_once()

from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncJsonWebsocketConsumer
from django.core.cache import cache
from django.db.models import F
from django.utils import timezone
from django.contrib.auth import get_user_model

from organizations.models import CustomerAccountMember

from .models import ChatConversation, ChatMessage, ChatParticipant
from .tasks import send_chat_push


class ChatConsumer(AsyncJsonWebsocketConsumer):
    async def connect(self):
        self.conversation_id = str(self.scope['url_route']['kwargs']['conversation_id'])
        self.room_group_name = f'chat_{self.conversation_id.replace("-", "")}'
        user = self.scope.get('user')
        account_id = await self._account_for_join(user.id, user.is_superuser) if user and user.is_authenticated else None
        if not account_id:
            await self.close(code=4403)
            return
        self.account_id = account_id
        await self.channel_layer.group_add(self.room_group_name, self.channel_name)
        await self.accept()
        await self._mark_read(user.id)
        await self._set_presence(user.id, True)
        await self.channel_layer.group_send(self.room_group_name, {
            'type': 'chat.presence', 'user_id': user.id, 'online': True,
        })

    async def disconnect(self, close_code):
        if hasattr(self, 'room_group_name'):
            user = self.scope.get('user')
            if user and user.is_authenticated and hasattr(self, 'account_id'):
                await self._set_presence(user.id, False)
                await self.channel_layer.group_send(self.room_group_name, {
                    'type': 'chat.presence', 'user_id': user.id, 'online': False,
                })
            await self.channel_layer.group_discard(self.room_group_name, self.channel_name)

    async def receive_json(self, content, **kwargs):
        if content.get('type') == 'heartbeat':
            await self._set_presence(self.scope['user'].id, True)
            await self.send_json({'type': 'heartbeat'})
            return
        body = str(content.get('body', '')).strip()
        if not body:
            return
        message = await self._save_message(self.scope['user'].id, body[:4000])
        if not message:
            await self.close(code=4403)
            return
        await self.channel_layer.group_send(self.room_group_name, {'type': 'chat.message', 'message': message})

    async def chat_message(self, event):
        await self.send_json({'type': 'message', **event['message']})

    async def chat_presence(self, event):
        await self.send_json({'type': 'presence', 'user_id': event['user_id'], 'online': event['online']})

    @database_sync_to_async
    def _account_for_join(self, user_id, is_superuser):
        conversation = ChatConversation.objects.filter(id=self.conversation_id).first()
        if not conversation:
            return None
        if is_superuser:
            return str(conversation.account_id)
        allowed = CustomerAccountMember.objects.filter(
            account=conversation.account, user_id=user_id, is_active=True,
        ).exists() and ChatParticipant.objects.filter(conversation=conversation, user_id=user_id).exists()
        return str(conversation.account_id) if allowed else None

    @database_sync_to_async
    def _mark_read(self, user_id):
        ChatParticipant.objects.filter(conversation_id=self.conversation_id, user_id=user_id).update(
            last_read_at=timezone.now(), unread_count=0,
        )

    @database_sync_to_async
    def _set_presence(self, user_id, online):
        key = f'chat_online:{self.account_id}:{user_id}'
        if online:
            cache.set(key, True, timeout=90)
        else:
            cache.delete(key)

    @database_sync_to_async
    def _save_message(self, user_id, body):
        participant = ChatParticipant.objects.filter(
            conversation_id=self.conversation_id, user_id=user_id,
            conversation__status='open',
        ).select_related('user', 'conversation').first()
        if participant:
            user = participant.user
            conversation = participant.conversation
        else:
            user = get_user_model().objects.filter(id=user_id, is_superuser=True).first()
            conversation = ChatConversation.objects.filter(id=self.conversation_id, status='open').first()
            if not user or not conversation:
                return None
        message = ChatMessage.objects.create(
            conversation=conversation, sender=user,
            sender_name=user.get_full_name() or user.username, body=body,
        )
        conversation.save(update_fields=['updated_at'])
        ChatParticipant.objects.filter(conversation=conversation).exclude(user_id=user.id).update(
            unread_count=F('unread_count') + 1,
        )
        if participant:
            participant.last_read_at = timezone.now()
            participant.unread_count = 0
            participant.save(update_fields=['last_read_at', 'unread_count'])
        send_chat_push.delay(message.id)
        return {
            'id': message.id, 'body': message.body, 'sender_name': message.sender_name,
            'sender_id': user.id, 'created_at': message.created_at.isoformat(),
        }

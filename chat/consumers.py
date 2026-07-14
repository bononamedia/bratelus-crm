from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncJsonWebsocketConsumer
from django.utils import timezone
from django.contrib.auth import get_user_model

from organizations.models import CustomerAccountMember

from .models import ChatConversation, ChatMessage, ChatParticipant


class ChatConsumer(AsyncJsonWebsocketConsumer):
    async def connect(self):
        self.conversation_id = str(self.scope['url_route']['kwargs']['conversation_id'])
        self.room_group_name = f'chat_{self.conversation_id.replace("-", "")}'
        user = self.scope.get('user')
        if not user or not user.is_authenticated or not await self._can_join(user.id, user.is_superuser):
            await self.close(code=4403)
            return
        await self.channel_layer.group_add(self.room_group_name, self.channel_name)
        await self.accept()
        await self._mark_read(user.id)

    async def disconnect(self, close_code):
        if hasattr(self, 'room_group_name'):
            await self.channel_layer.group_discard(self.room_group_name, self.channel_name)

    async def receive_json(self, content, **kwargs):
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

    @database_sync_to_async
    def _can_join(self, user_id, is_superuser):
        conversation = ChatConversation.objects.filter(id=self.conversation_id).first()
        if not conversation:
            return False
        if is_superuser:
            return True
        return CustomerAccountMember.objects.filter(
            account=conversation.account, user_id=user_id, is_active=True,
        ).exists() and ChatParticipant.objects.filter(conversation=conversation, user_id=user_id).exists()

    @database_sync_to_async
    def _mark_read(self, user_id):
        ChatParticipant.objects.filter(conversation_id=self.conversation_id, user_id=user_id).update(last_read_at=timezone.now())

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
        if participant:
            participant.last_read_at = timezone.now()
            participant.save(update_fields=['last_read_at'])
        return {
            'id': message.id, 'body': message.body, 'sender_name': message.sender_name,
            'sender_id': user.id, 'created_at': message.created_at.isoformat(),
        }

import json

from celery import shared_task
from django.conf import settings
from pywebpush import WebPushException, webpush

from .models import ChatMessage, WebPushSubscription


@shared_task
def send_chat_push(message_id):
    if not settings.CHAT_VAPID_PUBLIC_KEY or not settings.CHAT_VAPID_PRIVATE_KEY:
        return {'status': 'not_configured'}
    message = ChatMessage.objects.filter(id=message_id).select_related('conversation', 'sender').first()
    if not message or message.message_type != 'text':
        return {'status': 'ignored'}
    recipient_ids = message.conversation.participants.exclude(user_id=message.sender_id).values_list('user_id', flat=True)
    subscriptions = WebPushSubscription.objects.filter(user_id__in=recipient_ids)
    payload = json.dumps({
        'title': message.conversation.title,
        'body': f'{message.sender_name}: {message.body[:180]}',
        'url': f'/chat/{message.conversation_id}/',
        'conversation_id': str(message.conversation_id),
    })
    sent = 0
    for subscription in subscriptions:
        try:
            webpush(
                subscription_info={
                    'endpoint': subscription.endpoint,
                    'keys': {'p256dh': subscription.p256dh, 'auth': subscription.auth},
                },
                data=payload,
                vapid_private_key=settings.CHAT_VAPID_PRIVATE_KEY,
                vapid_claims={'sub': settings.CHAT_VAPID_SUBJECT},
                timeout=10,
            )
            sent += 1
        except WebPushException as exc:
            status_code = getattr(getattr(exc, 'response', None), 'status_code', None)
            if status_code in (404, 410):
                subscription.delete()
    return {'status': 'sent', 'count': sent}

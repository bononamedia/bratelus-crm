from django.contrib import messages
import json
import re
import uuid

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.core.cache import cache
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.db.models import F
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_http_methods, require_POST
from django.views.decorators.csrf import csrf_exempt

from fsm.models import Job
from organizations.models import CustomerAccountMember
from organizations.permissions import account_workspaces_for_user, user_can_manage_customer_account

from crm.models.contacts import Contact

from .models import (
    ChatConversation,
    ChatMessage,
    ChatParticipant,
    WebsiteChatWidget,
    WebPushSubscription,
)
from .permissions import account_for_request, user_in_account
from .tasks import send_chat_push


def _conversation_for_user(user, conversation_id, account):
    conversations = ChatConversation.objects.filter(id=conversation_id, account=account).prefetch_related('participants__user')
    if not user.is_superuser:
        conversations = conversations.filter(participants__user=user)
    return get_object_or_404(conversations.distinct())


@login_required
def chat_inbox_view(request, conversation_id=None):
    account = account_for_request(request)
    if not user_in_account(request.user, account):
        raise PermissionDenied('An active account membership is required for team chat.')
    workspace = getattr(request, 'active_organization', None)
    workspaces = account_workspaces_for_user(request.user, workspace).order_by('name')
    conversations = ChatConversation.objects.filter(
        account=account,
        participants__user=request.user,
        participants__archived_at__isnull=True,
    ).select_related(
        'workspace', 'job', 'contact'
    ).prefetch_related('participants__user', 'messages').distinct()
    if request.user.is_superuser:
        conversations = ChatConversation.objects.filter(account=account).select_related('workspace', 'job', 'contact').prefetch_related(
            'participants__user', 'messages'
        )
    conversations = list(conversations)
    for conversation in conversations:
        participant = next((item for item in conversation.participants.all() if item.user_id == request.user.id), None)
        conversation.user_unread_count = participant.unread_count if participant else 0
        conversation.online_count = sum(
            1 for item in conversation.participants.all()
            if item.user_id != request.user.id and cache.get(f'chat_online:{account.id}:{item.user_id}')
        )

    if request.method == 'POST':
        title = request.POST.get('title', '').strip()
        participant_ids = set(request.POST.getlist('participant_ids'))
        workspace_id = request.POST.get('workspace_id', '').strip()
        selected_workspace = workspaces.filter(id=workspace_id).first() if workspace_id else None
        if not title:
            messages.error(request, 'Enter a conversation title.')
            return redirect('chat_inbox')
        allowed_users = CustomerAccountMember.objects.filter(
            account=account, is_active=True, user_id__in=participant_ids,
        ).values_list('user_id', flat=True)
        with transaction.atomic():
            conversation = ChatConversation.objects.create(
                account=account, workspace=selected_workspace, title=title[:180], created_by=request.user,
            )
            participant_ids = set(allowed_users) | {request.user.id}
            ChatParticipant.objects.bulk_create([
                ChatParticipant(conversation=conversation, user_id=user_id) for user_id in participant_ids
            ])
            ChatMessage.objects.create(
                conversation=conversation, sender=request.user,
                sender_name=request.user.get_full_name() or request.user.username,
                message_type='system', body='Conversation created.',
            )
        return redirect('chat_conversation', conversation_id=conversation.id)

    selected = None
    chat_messages = []
    if conversation_id:
        selected = _conversation_for_user(request.user, conversation_id, account)
        chat_messages = selected.messages.select_related('sender').all()
        ChatParticipant.objects.filter(conversation=selected, user=request.user).update(
            last_read_at=timezone.now(), unread_count=0,
        )
        for participant in selected.participants.all():
            participant.is_online = bool(cache.get(f'chat_online:{account.id}:{participant.user_id}'))
    members = CustomerAccountMember.objects.filter(account=account, is_active=True).select_related('user').order_by(
        'user__first_name', 'user__last_name', 'user__username'
    )
    jobs = Job.objects.filter(organization__in=workspaces).exclude(status__in=['canceled']).select_related(
        'organization', 'account'
    ).order_by('-scheduled_start', '-id')[:250]
    return render(request, 'chat/inbox.html', {
        'conversations': conversations,
        'selected_conversation': selected,
        'chat_messages': chat_messages,
        'members': members,
        'workspaces': workspaces,
        'jobs': jobs,
        'chat_vapid_public_key': settings.CHAT_VAPID_PUBLIC_KEY,
        'can_manage_chat': user_can_manage_customer_account(request.user, account),
    })


@login_required
@require_POST
def chat_attach_job_view(request, conversation_id):
    account = account_for_request(request)
    conversation = _conversation_for_user(request.user, conversation_id, account)
    workspaces = account_workspaces_for_user(request.user, getattr(request, 'active_organization', None))
    job = get_object_or_404(Job, id=request.POST.get('job_id'), organization__in=workspaces)
    conversation.job = job
    conversation.workspace = job.organization
    conversation.transcript_attached_at = timezone.now()
    conversation.save(update_fields=['job', 'workspace', 'transcript_attached_at', 'updated_at'])
    ChatMessage.objects.create(
        conversation=conversation, sender=request.user,
        sender_name=request.user.get_full_name() or request.user.username,
        message_type='system', body=f'Transcript attached to job #{job.id}: {job.title}.',
    )
    messages.success(request, f'Conversation attached to job #{job.id}.')
    return redirect('chat_conversation', conversation_id=conversation.id)


@login_required
@require_POST
def chat_conversation_action_view(request, conversation_id):
    account = account_for_request(request)
    conversation = _conversation_for_user(request.user, conversation_id, account)
    action_name = request.POST.get('action', '').strip()
    if action_name == 'archive':
        participant, _ = ChatParticipant.objects.get_or_create(
            conversation=conversation,
            user=request.user,
        )
        participant.archived_at = timezone.now()
        participant.save(update_fields=['archived_at'])
        return redirect('chat_inbox')
    if not user_can_manage_customer_account(request.user, account):
        raise PermissionDenied('Only an account manager can close or delete a conversation.')
    if action_name in {'close', 'reopen'}:
        conversation.status = 'closed' if action_name == 'close' else 'open'
        conversation.save(update_fields=['status', 'updated_at'])
        ChatMessage.objects.create(
            conversation=conversation,
            sender=request.user,
            sender_name=request.user.get_full_name() or request.user.username,
            message_type='system',
            body='Conversation closed.' if action_name == 'close' else 'Conversation reopened.',
        )
        return redirect('chat_conversation', conversation_id=conversation.id)
    if action_name == 'delete':
        conversation.delete()
        messages.success(request, 'Conversation permanently deleted.')
        return redirect('chat_inbox')
    return JsonResponse({'error': 'Choose a valid conversation action.'}, status=400)


def _broadcast_chat_message(message):
    async_to_sync(get_channel_layer().group_send)(
        f'chat_{str(message.conversation_id).replace("-", "")}',
        {
            'type': 'chat.message',
            'message': {
                'id': message.id,
                'body': message.body,
                'sender_name': message.sender_name,
                'sender_id': message.sender_id,
                'created_at': message.created_at.isoformat(),
            },
        },
    )


@login_required
@require_http_methods(['GET', 'POST'])
def website_chat_settings_view(request):
    workspace = getattr(request, 'active_organization', None)
    if not workspace or not user_can_manage_customer_account(request.user, workspace.customer_account):
        raise PermissionDenied('Only an account manager can configure website chat.')
    widget, _ = WebsiteChatWidget.objects.get_or_create(workspace=workspace)
    if request.method == 'POST':
        color = request.POST.get('brand_color', '').strip()
        if not re.fullmatch(r'#[0-9a-fA-F]{6}', color):
            color = '#2563eb'
        widget.brand_color = color
        widget.greeting = request.POST.get('greeting', '').strip()[:180] or 'Hi! How can our team help you today?'
        widget.is_enabled = request.POST.get('is_enabled') == 'on'
        widget.require_email = request.POST.get('require_email') == 'on'
        widget.save()
        messages.success(request, 'Website chat settings updated.')
        return redirect('website_chat_settings')
    launcher_url = request.build_absolute_uri(
        reverse('website_chat_launcher', args=[widget.public_key])
    )
    return render(request, 'chat/website_settings.html', {
        'widget': widget,
        'launcher_url': launcher_url,
    })


@require_http_methods(['GET'])
def website_chat_launcher_view(request, public_key):
    widget = get_object_or_404(
        WebsiteChatWidget.objects.select_related('workspace'),
        public_key=public_key,
        is_enabled=True,
    )
    widget_url = request.build_absolute_uri(reverse('website_chat_widget', args=[widget.public_key]))
    script = f"""
(() => {{
  if (document.getElementById('bratelus-chat-launcher')) return;
  const wrap=document.createElement('div'); wrap.id='bratelus-chat-launcher';
  wrap.style.cssText='position:fixed;right:20px;bottom:20px;z-index:2147483000;font-family:Arial,sans-serif';
  const frame=document.createElement('iframe'); frame.src={json.dumps(widget_url + '?page=')}+encodeURIComponent(location.href);
  frame.title='Chat with us'; frame.style.cssText='display:none;width:min(380px,calc(100vw - 24px));height:min(620px,calc(100vh - 90px));border:0;border-radius:10px;box-shadow:0 18px 50px rgba(0,0,0,.24);background:white;margin-bottom:10px';
  const button=document.createElement('button'); button.type='button'; button.setAttribute('aria-label','Open chat');
  button.textContent='Chat'; button.style.cssText='float:right;border:0;border-radius:999px;background:{widget.brand_color};color:white;padding:13px 20px;font-weight:700;box-shadow:0 8px 24px rgba(0,0,0,.22);cursor:pointer';
  button.onclick=()=>{{const open=frame.style.display!=='none';frame.style.display=open?'none':'block';button.textContent=open?'Chat':'Close';}};
  wrap.append(frame,button); document.body.appendChild(wrap);
}})();
"""
    return HttpResponse(script, content_type='application/javascript')


@csrf_exempt
@require_http_methods(['GET', 'POST'])
def website_chat_widget_view(request, public_key):
    widget = get_object_or_404(
        WebsiteChatWidget.objects.select_related('workspace__customer_account'),
        public_key=public_key,
        is_enabled=True,
    )
    session_key = f'website_chat_{widget.public_key}'
    visitor_key = request.POST.get('visitor_key') or request.GET.get('visitor_key') or request.session.get(session_key)
    try:
        visitor_key = str(uuid.UUID(str(visitor_key))) if visitor_key else None
    except (ValueError, TypeError, AttributeError):
        visitor_key = None
    conversation = ChatConversation.objects.filter(
        visitor_key=visitor_key,
        workspace=widget.workspace,
        origin='website',
    ).first() if visitor_key else None

    if request.method == 'POST':
        remote_address = request.META.get('HTTP_X_FORWARDED_FOR', request.META.get('REMOTE_ADDR', '')).split(',')[0].strip()
        throttle_key = f'website_chat_rate:{widget.public_key}:{remote_address}'
        request_count = cache.get(throttle_key, 0)
        if request_count >= 30:
            return JsonResponse({'error': 'Please wait before sending another message.'}, status=429)
        cache.set(throttle_key, request_count + 1, 60)
        body = request.POST.get('body', '').strip()
        if not body:
            return JsonResponse({'error': 'Enter a message.'}, status=400)
        if not conversation:
            visitor_name = request.POST.get('visitor_name', '').strip()[:120]
            visitor_email = request.POST.get('visitor_email', '').strip().lower()
            if not visitor_name or (widget.require_email and not visitor_email):
                return JsonResponse({'error': 'Enter your name and email.'}, status=400)
            contact = None
            if visitor_email:
                contact = Contact.objects.filter(
                    organization=widget.workspace,
                    email__iexact=visitor_email,
                    archived_at__isnull=True,
                ).first()
            if not contact:
                parts = visitor_name.split(None, 1)
                contact = Contact.objects.create(
                    organization=widget.workspace,
                    first_name=parts[0] if parts else 'Website',
                    last_name=parts[1] if len(parts) > 1 else 'Visitor',
                    email=visitor_email,
                    lead_source='Website Chat',
                    status='Lead',
                    external_source='bratelus_website_chat',
                )
            conversation = ChatConversation.objects.create(
                account=widget.workspace.customer_account,
                workspace=widget.workspace,
                origin='website',
                title=f'Website: {visitor_name or visitor_email}'[:180],
                visitor_name=visitor_name,
                visitor_email=visitor_email,
                visitor_page_url=request.POST.get('page_url', '')[:1000],
                contact=contact,
            )
            manager_ids = CustomerAccountMember.objects.filter(
                account=conversation.account,
                is_active=True,
                role__in=['owner', 'admin', 'manager'],
            ).values_list('user_id', flat=True)
            ChatParticipant.objects.bulk_create([
                ChatParticipant(conversation=conversation, user_id=user_id)
                for user_id in manager_ids
            ], ignore_conflicts=True)
            request.session[session_key] = str(conversation.visitor_key)
        message = ChatMessage.objects.create(
            conversation=conversation,
            sender_name=conversation.visitor_name or 'Website visitor',
            body=body[:4000],
        )
        conversation.save(update_fields=['updated_at'])
        ChatParticipant.objects.filter(conversation=conversation).update(
            unread_count=F('unread_count') + 1,
        )
        _broadcast_chat_message(message)
        send_chat_push.delay(message.id)
        return JsonResponse({
            'id': message.id,
            'message': 'sent',
            'visitor_key': str(conversation.visitor_key),
        }, status=201)

    chat_messages = conversation.messages.all() if conversation else []
    if request.GET.get('format') == 'json':
        return JsonResponse({
            'messages': [
                {
                    'id': message.id,
                    'body': message.body,
                    'sender_name': message.sender_name,
                    'is_visitor': message.sender_id is None and message.message_type == 'text',
                    'created_at': message.created_at.isoformat(),
                }
                for message in chat_messages
            ],
            'status': conversation.status if conversation else 'new',
        })
    return render(request, 'chat/widget.html', {
        'widget': widget,
        'conversation': conversation,
        'chat_messages': chat_messages,
        'source_page': request.GET.get('page', '')[:1000],
    })


@login_required
@require_POST
def chat_message_view(request, conversation_id):
    account = account_for_request(request)
    conversation = _conversation_for_user(request.user, conversation_id, account)
    if conversation.status != 'open':
        return JsonResponse({'error': 'This conversation is closed.'}, status=400)
    body = request.POST.get('body', '').strip()
    if not body:
        return JsonResponse({'error': 'Enter a message.'}, status=400)
    message = ChatMessage.objects.create(
        conversation=conversation, sender=request.user,
        sender_name=request.user.get_full_name() or request.user.username, body=body[:4000],
    )
    conversation.save(update_fields=['updated_at'])
    ChatParticipant.objects.filter(conversation=conversation).exclude(user=request.user).update(
        unread_count=F('unread_count') + 1,
    )
    ChatParticipant.objects.filter(conversation=conversation, user=request.user).update(
        last_read_at=timezone.now(), unread_count=0,
    )
    send_chat_push.delay(message.id)
    return JsonResponse({
        'id': message.id, 'body': message.body, 'sender_name': message.sender_name,
        'sender_id': request.user.id, 'created_at': message.created_at.isoformat(),
    }, status=201)


@login_required
@require_POST
def chat_push_subscribe_view(request):
    try:
        data = json.loads(request.body)
        endpoint = data['endpoint']
        p256dh = data['keys']['p256dh']
        auth = data['keys']['auth']
    except (KeyError, TypeError, ValueError, json.JSONDecodeError):
        return JsonResponse({'error': 'Invalid push subscription.'}, status=400)
    if not endpoint.startswith('https://'):
        return JsonResponse({'error': 'A secure push endpoint is required.'}, status=400)
    WebPushSubscription.objects.update_or_create(
        endpoint=endpoint,
        defaults={
            'user': request.user, 'p256dh': p256dh[:255], 'auth': auth[:255],
            'user_agent': request.headers.get('User-Agent', '')[:500],
        },
    )
    return JsonResponse({'status': 'subscribed'})


@login_required
@require_POST
def chat_push_unsubscribe_view(request):
    try:
        endpoint = json.loads(request.body).get('endpoint', '')
    except json.JSONDecodeError:
        endpoint = ''
    WebPushSubscription.objects.filter(user=request.user, endpoint=endpoint).delete()
    return JsonResponse({'status': 'unsubscribed'})


def chat_service_worker_view(request):
    script = """
self.addEventListener('push', event => {
  const data = event.data ? event.data.json() : {};
  event.waitUntil(self.registration.showNotification(data.title || 'Bratelus Team Chat', {
    body: data.body || 'You have a new message.',
    data: {url: data.url || '/chat/'},
    tag: data.conversation_id || 'bratelus-chat'
  }));
});
self.addEventListener('notificationclick', event => {
  event.notification.close();
  const url = new URL(event.notification.data.url || '/chat/', self.location.origin).href;
  event.waitUntil(clients.matchAll({type: 'window', includeUncontrolled: true}).then(list => {
    for (const client of list) { if (client.url === url && 'focus' in client) return client.focus(); }
    return clients.openWindow ? clients.openWindow(url) : null;
  }));
});
"""
    response = HttpResponse(script, content_type='application/javascript')
    response['Service-Worker-Allowed'] = '/'
    response['Cache-Control'] = 'no-cache'
    return response

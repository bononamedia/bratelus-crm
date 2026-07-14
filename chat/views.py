from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from fsm.models import Job
from organizations.models import CustomerAccountMember
from organizations.permissions import account_workspaces_for_user

from .models import ChatConversation, ChatMessage, ChatParticipant
from .permissions import account_for_request, user_in_account


def _conversation_for_user(user, conversation_id, account):
    conversations = ChatConversation.objects.filter(id=conversation_id, account=account)
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
    conversations = ChatConversation.objects.filter(account=account, participants__user=request.user).select_related(
        'workspace', 'job'
    ).prefetch_related('participants__user', 'messages').distinct()
    if request.user.is_superuser:
        conversations = ChatConversation.objects.filter(account=account).select_related('workspace', 'job').prefetch_related(
            'participants__user', 'messages'
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
        ChatParticipant.objects.filter(conversation=selected, user=request.user).update(last_read_at=timezone.now())
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
    return JsonResponse({
        'id': message.id, 'body': message.body, 'sender_name': message.sender_name,
        'sender_id': request.user.id, 'created_at': message.created_at.isoformat(),
    }, status=201)

import uuid

from django.contrib.auth.models import User
from django.db import models

from fsm.models import Job
from organizations.models import CustomerAccount, Workspace


class ChatConversation(models.Model):
    ORIGIN_CHOICES = [('internal', 'Internal team'), ('website', 'Website visitor')]
    STATUS_CHOICES = [('open', 'Open'), ('closed', 'Closed')]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    account = models.ForeignKey(CustomerAccount, on_delete=models.CASCADE, related_name='chat_conversations')
    workspace = models.ForeignKey(Workspace, on_delete=models.SET_NULL, null=True, blank=True, related_name='chat_conversations')
    job = models.ForeignKey(Job, on_delete=models.SET_NULL, null=True, blank=True, related_name='chat_conversations')
    origin = models.CharField(max_length=20, choices=ORIGIN_CHOICES, default='internal')
    title = models.CharField(max_length=180)
    status = models.CharField(max_length=12, choices=STATUS_CHOICES, default='open')
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='created_chat_conversations')
    visitor_name = models.CharField(max_length=120, blank=True)
    visitor_email = models.EmailField(blank=True)
    transcript_attached_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ('-updated_at',)

    def __str__(self):
        return self.title


class ChatParticipant(models.Model):
    conversation = models.ForeignKey(ChatConversation, on_delete=models.CASCADE, related_name='participants')
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='chat_participations')
    joined_at = models.DateTimeField(auto_now_add=True)
    last_read_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        unique_together = ('conversation', 'user')


class ChatMessage(models.Model):
    MESSAGE_TYPE_CHOICES = [('text', 'Text'), ('system', 'System')]

    conversation = models.ForeignKey(ChatConversation, on_delete=models.CASCADE, related_name='messages')
    sender = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='chat_messages')
    sender_name = models.CharField(max_length=150, blank=True)
    body = models.TextField(max_length=4000)
    message_type = models.CharField(max_length=12, choices=MESSAGE_TYPE_CHOICES, default='text')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ('created_at', 'id')
        indexes = [models.Index(fields=('conversation', 'created_at'), name='chat_message_conversation_time')]

    def __str__(self):
        return f'{self.sender_name}: {self.body[:60]}'

import uuid

from django.contrib.auth.models import User
from django.db import models

from fsm.models import Job
from crm.models.contacts import Contact
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
    visitor_key = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)
    visitor_page_url = models.URLField(max_length=1000, blank=True)
    contact = models.ForeignKey(
        Contact,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='chat_conversations',
    )
    transcript_attached_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ('-updated_at',)

    def __str__(self):
        return self.title


class WebsiteChatWidget(models.Model):
    workspace = models.OneToOneField(
        Workspace,
        on_delete=models.CASCADE,
        related_name='website_chat_widget',
    )
    public_key = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)
    is_enabled = models.BooleanField(default=False)
    brand_color = models.CharField(max_length=7, default='#2563eb')
    greeting = models.CharField(
        max_length=180,
        default='Hi! How can our team help you today?',
    )
    require_email = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f'{self.workspace.name} website chat'


class ChatParticipant(models.Model):
    conversation = models.ForeignKey(ChatConversation, on_delete=models.CASCADE, related_name='participants')
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='chat_participations')
    joined_at = models.DateTimeField(auto_now_add=True)
    last_read_at = models.DateTimeField(null=True, blank=True)
    unread_count = models.PositiveIntegerField(default=0)
    archived_at = models.DateTimeField(null=True, blank=True)

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


class WebPushSubscription(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='chat_push_subscriptions')
    endpoint = models.URLField(max_length=1000, unique=True)
    p256dh = models.CharField(max_length=255)
    auth = models.CharField(max_length=255)
    user_agent = models.CharField(max_length=500, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ('-updated_at',)

    def __str__(self):
        return f'{self.user} / {self.endpoint[:60]}'

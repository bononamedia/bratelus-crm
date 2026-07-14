from django.contrib import admin

from .models import ChatConversation, ChatMessage, ChatParticipant, WebPushSubscription


admin.site.register(ChatConversation)
admin.site.register(ChatParticipant)
admin.site.register(ChatMessage)
admin.site.register(WebPushSubscription)

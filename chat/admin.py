from django.contrib import admin

from .models import ChatConversation, ChatMessage, ChatParticipant, WebsiteChatWidget, WebPushSubscription


admin.site.register(ChatConversation)
admin.site.register(WebsiteChatWidget)
admin.site.register(ChatParticipant)
admin.site.register(ChatMessage)
admin.site.register(WebPushSubscription)

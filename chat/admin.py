from django.contrib import admin

from .models import ChatConversation, ChatMessage, ChatParticipant


admin.site.register(ChatConversation)
admin.site.register(ChatParticipant)
admin.site.register(ChatMessage)

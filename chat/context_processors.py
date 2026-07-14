from django.db.models import Sum

from .models import ChatParticipant


def chat_context(request):
    if not request.user.is_authenticated:
        return {}
    unread = ChatParticipant.objects.filter(user=request.user).aggregate(total=Sum('unread_count'))['total'] or 0
    return {'unread_chat_count': unread}

from celery import shared_task
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string
from django.utils import timezone

from finance.models import WorkspaceSubscription
from organizations.models import UserEmailVerification, Workspace
from organizations.emailing import platform_email_delivery


def _send_template_email(subject, template_name, context, recipient):
    text = render_to_string(f'emails/{template_name}.txt', context)
    html = render_to_string(f'emails/{template_name}.html', context)
    connection, from_email, _ = platform_email_delivery()
    email = EmailMultiAlternatives(subject, text, from_email, [recipient], connection=connection)
    email.attach_alternative(html, 'text/html')
    email.send(fail_silently=False)


@shared_task(autoretry_for=(Exception,), retry_backoff=True, max_retries=3)
def send_signup_welcome_email(user_id, workspace_id, verification_url):
    user = get_user_model().objects.get(id=user_id)
    workspace = Workspace.objects.select_related('customer_account').get(id=workspace_id)
    subscription = WorkspaceSubscription.objects.select_related('plan').filter(workspace=workspace).first()
    context = {
        'user': user,
        'workspace': workspace,
        'subscription': subscription,
        'verification_url': verification_url,
        'billing_url': f'{settings.APP_BASE_URL.rstrip("/")}/billing/',
        'base_price': subscription.plan.base_monthly_amount if subscription else 49,
    }
    _send_template_email('Welcome to Bratelus - verify your email', 'signup_welcome', context, user.email)
    UserEmailVerification.objects.update_or_create(user=user, defaults={'sent_at': timezone.now()})


@shared_task(autoretry_for=(Exception,), retry_backoff=True, max_retries=3)
def send_new_account_alert(user_id, workspace_id):
    user = get_user_model().objects.get(id=user_id)
    workspace = Workspace.objects.select_related('customer_account').get(id=workspace_id)
    subscription = WorkspaceSubscription.objects.select_related('plan').filter(workspace=workspace).first()
    context = {
        'user': user,
        'workspace': workspace,
        'subscription': subscription,
        'admin_url': f'{settings.APP_BASE_URL.rstrip("/")}/admin/organizations/customeraccount/{workspace.customer_account_id}/change/',
    }
    _, _, support_email = platform_email_delivery()
    _send_template_email(
        f'New Bratelus account: {workspace.customer_account.name}',
        'new_account_alert', context, support_email,
    )

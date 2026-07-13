from datetime import datetime, timezone as datetime_timezone
from decimal import Decimal

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.http import HttpResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from organizations.models import Workspace, WorkspaceMember
from organizations.permissions import user_can_manage_workspace

from .models import BillingEvent, PlatformInvoice, SubscriptionPlan, WorkspaceSubscription
from .pricing import monthly_price, pricing_breakdown


def _stripe():
    import stripe

    stripe.api_key = settings.STRIPE_SECRET_KEY
    return stripe


def _stripe_ready(plan=None):
    if not settings.STRIPE_SECRET_KEY:
        return False
    return not plan or bool(plan.stripe_base_price_id and plan.stripe_seat_price_id)


def _subscription_for(workspace):
    plan = SubscriptionPlan.objects.filter(is_active=True).prefetch_related('seat_tiers').first()
    if not plan:
        return None
    subscription, _ = WorkspaceSubscription.objects.get_or_create(
        workspace=workspace,
        defaults={'plan': plan, 'seat_count': 1},
    )
    return subscription


@login_required
def billing_overview_view(request):
    workspace = getattr(request, 'active_organization', None)
    if not user_can_manage_workspace(request.user, workspace):
        raise PermissionDenied('Only workspace admins can manage platform billing.')

    subscription = _subscription_for(workspace)
    active_users = WorkspaceMember.objects.filter(workspace=workspace, is_active=True).count()
    active_users = max(active_users, 1)
    if subscription and subscription.seat_count != active_users:
        subscription.seat_count = active_users
        subscription.save(update_fields=['seat_count', 'updated_at'])

    estimates = []
    if subscription:
        for count in sorted(set([active_users, active_users + 1, 5, 10, 25, 50, 100])):
            if count >= active_users:
                estimates.append({'users': count, 'amount': monthly_price(subscription.plan, count)})

    context = {
        'subscription': subscription,
        'active_users': active_users,
        'estimated_monthly': monthly_price(subscription.plan, active_users) if subscription else Decimal('0'),
        'pricing_breakdown': pricing_breakdown(subscription.plan, active_users) if subscription else [],
        'estimates': estimates,
        'platform_invoices': PlatformInvoice.objects.filter(workspace=workspace)[:24],
        'billing_events': BillingEvent.objects.filter(workspace=workspace)[:20],
        'stripe_ready': _stripe_ready(subscription.plan if subscription else None),
    }
    return render(request, 'billing_overview.html', context)


@login_required
@require_POST
def create_checkout_session_view(request):
    workspace = getattr(request, 'active_organization', None)
    if not user_can_manage_workspace(request.user, workspace):
        raise PermissionDenied
    subscription = _subscription_for(workspace)
    if not subscription or not _stripe_ready(subscription.plan):
        messages.error(request, 'Stripe prices are not configured yet. Add them in the platform superadmin.')
        return redirect('billing_overview')

    seats = max(WorkspaceMember.objects.filter(workspace=workspace, is_active=True).count(), 1)
    additional_seats = max(seats - subscription.plan.included_users, 0)
    line_items = [{'price': subscription.plan.stripe_base_price_id, 'quantity': 1}]
    if additional_seats:
        line_items.append({'price': subscription.plan.stripe_seat_price_id, 'quantity': additional_seats})

    stripe = _stripe()
    kwargs = {
        'mode': 'subscription',
        'line_items': line_items,
        'success_url': request.build_absolute_uri(reverse('billing_overview')) + '?checkout=success',
        'cancel_url': request.build_absolute_uri(reverse('billing_overview')) + '?checkout=canceled',
        'client_reference_id': str(workspace.id),
        'metadata': {'workspace_id': str(workspace.id), 'seat_count': str(seats)},
        'subscription_data': {'metadata': {'workspace_id': str(workspace.id)}},
        'allow_promotion_codes': True,
    }
    if subscription.stripe_customer_id:
        kwargs['customer'] = subscription.stripe_customer_id
    else:
        customer_email = subscription.billing_email or request.user.email
        if customer_email:
            kwargs['customer_email'] = customer_email
    session = stripe.checkout.Session.create(**kwargs)
    BillingEvent.objects.create(
        workspace=workspace,
        event_type='checkout.started',
        summary=f'Checkout started for {seats} users.',
        actor=request.user,
        metadata={'estimated_monthly': str(monthly_price(subscription.plan, seats))},
    )
    return redirect(session.url, permanent=False)


@login_required
@require_POST
def create_billing_portal_view(request):
    workspace = getattr(request, 'active_organization', None)
    if not user_can_manage_workspace(request.user, workspace):
        raise PermissionDenied
    subscription = _subscription_for(workspace)
    if not subscription or not subscription.stripe_customer_id or not settings.STRIPE_SECRET_KEY:
        messages.error(request, 'Complete Stripe checkout before opening the billing portal.')
        return redirect('billing_overview')
    session = _stripe().billing_portal.Session.create(
        customer=subscription.stripe_customer_id,
        return_url=request.build_absolute_uri(reverse('billing_overview')),
    )
    return redirect(session.url, permanent=False)


def sync_subscription_seats(subscription, seat_count):
    subscription.seat_count = max(int(seat_count), 1)
    subscription.save(update_fields=['seat_count', 'updated_at'])
    if not (settings.STRIPE_SECRET_KEY and subscription.stripe_subscription_id):
        return False
    additional = max(subscription.seat_count - subscription.plan.included_users, 0)
    if additional and subscription.stripe_seat_item_id:
        _stripe().SubscriptionItem.modify(
            subscription.stripe_seat_item_id,
            quantity=additional,
            proration_behavior='create_prorations',
        )
    elif additional and subscription.plan.stripe_seat_price_id:
        item = _stripe().SubscriptionItem.create(
            subscription=subscription.stripe_subscription_id,
            price=subscription.plan.stripe_seat_price_id,
            quantity=additional,
            proration_behavior='create_prorations',
        )
        subscription.stripe_seat_item_id = item.id
        subscription.save(update_fields=['stripe_seat_item_id', 'updated_at'])
    return True


def _as_datetime(timestamp):
    return datetime.fromtimestamp(timestamp, tz=datetime_timezone.utc) if timestamp else None


def _sync_subscription_object(obj):
    customer_id = obj.get('customer', '')
    subscription = WorkspaceSubscription.objects.filter(stripe_subscription_id=obj.get('id')).first()
    if not subscription and customer_id:
        subscription = WorkspaceSubscription.objects.filter(stripe_customer_id=customer_id).first()
    if not subscription:
        workspace_id = (obj.get('metadata') or {}).get('workspace_id')
        workspace = Workspace.objects.filter(id=workspace_id).first() if workspace_id else None
        subscription = _subscription_for(workspace) if workspace else None
    if not subscription:
        return None
    items = ((obj.get('items') or {}).get('data') or [])
    seat_item = next(
        (item for item in items if (item.get('price') or {}).get('id') == subscription.plan.stripe_seat_price_id),
        None,
    )
    subscription.stripe_customer_id = customer_id or subscription.stripe_customer_id
    subscription.stripe_subscription_id = obj.get('id', subscription.stripe_subscription_id)
    subscription.stripe_seat_item_id = (seat_item or {}).get('id', subscription.stripe_seat_item_id)
    subscription.status = obj.get('status', subscription.status)
    subscription.current_period_start = _as_datetime(obj.get('current_period_start'))
    subscription.current_period_end = _as_datetime(obj.get('current_period_end'))
    subscription.cancel_at_period_end = bool(obj.get('cancel_at_period_end'))
    subscription.save()
    return subscription


@csrf_exempt
@require_POST
def stripe_webhook_view(request):
    if not settings.STRIPE_WEBHOOK_SECRET:
        return HttpResponse(status=503)
    stripe = _stripe()
    try:
        event = stripe.Webhook.construct_event(
            request.body,
            request.META.get('HTTP_STRIPE_SIGNATURE', ''),
            settings.STRIPE_WEBHOOK_SECRET,
        )
    except ValueError:
        return HttpResponse(status=400)
    except stripe.error.SignatureVerificationError:
        return HttpResponse(status=400)

    event_id = event.get('id')
    if BillingEvent.objects.filter(stripe_event_id=event_id).exists():
        return HttpResponse(status=200)
    event_type = event.get('type', '')
    obj = event['data']['object']
    subscription = None

    if event_type == 'checkout.session.completed':
        workspace = Workspace.objects.filter(id=(obj.get('metadata') or {}).get('workspace_id')).first()
        subscription = _subscription_for(workspace) if workspace else None
        if subscription:
            subscription.stripe_customer_id = obj.get('customer', '')
            subscription.stripe_subscription_id = obj.get('subscription', '')
            subscription.status = 'active' if obj.get('payment_status') == 'paid' else 'incomplete'
            subscription.save()
    elif event_type.startswith('customer.subscription.'):
        subscription = _sync_subscription_object(obj)
    elif event_type.startswith('invoice.'):
        subscription = WorkspaceSubscription.objects.filter(stripe_customer_id=obj.get('customer', '')).first()
        if subscription:
            PlatformInvoice.objects.update_or_create(
                stripe_invoice_id=obj.get('id'),
                defaults={
                    'workspace': subscription.workspace,
                    'subscription': subscription,
                    'invoice_number': obj.get('number') or '',
                    'status': obj.get('status') or '',
                    'currency': obj.get('currency') or 'usd',
                    'amount_due': Decimal(obj.get('amount_due') or 0) / 100,
                    'amount_paid': Decimal(obj.get('amount_paid') or 0) / 100,
                    'hosted_invoice_url': obj.get('hosted_invoice_url') or '',
                    'invoice_pdf_url': obj.get('invoice_pdf') or '',
                    'period_start': _as_datetime(obj.get('period_start')),
                    'period_end': _as_datetime(obj.get('period_end')),
                },
            )

    BillingEvent.objects.create(
        workspace=subscription.workspace if subscription else None,
        event_type=event_type,
        stripe_event_id=event_id,
        summary=f'Stripe event received: {event_type}',
    )
    return HttpResponse(status=200)

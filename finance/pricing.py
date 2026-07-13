from decimal import Decimal


def monthly_price(plan, total_users):
    """Return a graduated monthly price for a workspace's total active users."""
    total_users = max(int(total_users or 1), 1)
    additional_seats = max(total_users - plan.included_users, 0)
    total = Decimal(plan.base_monthly_amount)

    for tier in plan.seat_tiers.all():
        if additional_seats < tier.first_seat:
            continue
        upper = tier.up_to_seat or additional_seats
        seats_in_tier = min(additional_seats, upper) - tier.first_seat + 1
        if seats_in_tier > 0:
            total += Decimal(seats_in_tier) * Decimal(tier.unit_amount)
    return total.quantize(Decimal('0.01'))


def pricing_breakdown(plan, total_users):
    total_users = max(int(total_users or 1), 1)
    additional_seats = max(total_users - plan.included_users, 0)
    rows = [{
        'label': f'Platform base ({plan.included_users} user included)',
        'quantity': 1,
        'unit_amount': plan.base_monthly_amount,
        'amount': plan.base_monthly_amount,
    }]
    for tier in plan.seat_tiers.all():
        if additional_seats < tier.first_seat:
            continue
        upper = tier.up_to_seat or additional_seats
        quantity = min(additional_seats, upper) - tier.first_seat + 1
        if quantity > 0:
            rows.append({
                'label': f'Additional users {tier.first_seat}-{tier.up_to_seat or "+"}',
                'quantity': quantity,
                'unit_amount': tier.unit_amount,
                'amount': (Decimal(quantity) * tier.unit_amount).quantize(Decimal('0.01')),
            })
    return rows

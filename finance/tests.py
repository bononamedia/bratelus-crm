from decimal import Decimal

from django.test import TestCase

from finance.models import SeatPricingTier, SubscriptionPlan
from finance.pricing import monthly_price


class GraduatedPricingTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.plan = SubscriptionPlan.objects.create(
            name='Full CRM', code='test-full-crm', base_monthly_amount=49, included_users=1
        )
        for first, up_to, amount in [(1, 5, 25), (6, 10, 20), (11, 50, 15), (51, None, 10)]:
            SeatPricingTier.objects.create(
                plan=cls.plan, first_seat=first, up_to_seat=up_to, unit_amount=amount, sort_order=first
            )

    def test_base_price_includes_one_user(self):
        self.assertEqual(monthly_price(self.plan, 1), Decimal('49.00'))

    def test_price_is_graduated_without_tier_cliffs(self):
        self.assertEqual(monthly_price(self.plan, 6), Decimal('174.00'))
        self.assertEqual(monthly_price(self.plan, 11), Decimal('274.00'))
        self.assertEqual(monthly_price(self.plan, 51), Decimal('874.00'))
        self.assertEqual(monthly_price(self.plan, 52), Decimal('884.00'))

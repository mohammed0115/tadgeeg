"""Tests for the official billing extend_subscription service (CRM-1F-1A)."""
from datetime import timedelta
from io import StringIO

from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone

from apps.billing.choices import PlanCode, SubscriptionStatus
from apps.billing.models import OrganizationSubscription, Plan
from apps.billing.services.subscription_service import (
    SubscriptionNotExtendable,
    SubscriptionService,
)
from apps.billing.tests._factories import make_org
from apps.payments.models import PaymentTransaction


class ExtendSubscriptionTests(TestCase):
    def setUp(self):
        call_command("seed_billing_plans", stdout=StringIO())
        self.org = make_org()
        self.svc = SubscriptionService()
        self.business = Plan.objects.get(code=PlanCode.BUSINESS)

    # ── builders ──────────────────────────────────────────────────────────────
    def _active_sub(self):
        sub = self.svc.create_pending_paid_subscription(self.org, self.business)
        return self.svc.activate_subscription(sub)

    def _trialing_sub(self):
        return self.svc.create_free_trial(self.org)

    def _sub_in_status(self, status):
        sub = self._active_sub()
        sub.status = status
        sub.save(update_fields=["status"])
        sub.refresh_from_db()
        return sub

    # ── happy paths ───────────────────────────────────────────────────────────
    def test_extend_active_adds_days(self):
        sub = self._active_sub()
        before = sub.ends_at
        out = self.svc.extend_subscription(sub, days=15)
        self.assertEqual(out.ends_at, before + timedelta(days=15))
        self.assertEqual(out.status, SubscriptionStatus.ACTIVE)

    def test_extend_trialing_adds_days(self):
        sub = self._trialing_sub()
        self.assertEqual(sub.status, SubscriptionStatus.TRIALING)
        before = sub.ends_at
        out = self.svc.extend_subscription(sub, days=7)
        self.assertEqual(out.ends_at, before + timedelta(days=7))

    def test_extend_persists_to_db(self):
        sub = self._active_sub()
        before = sub.ends_at
        self.svc.extend_subscription(sub, days=10)
        fresh = OrganizationSubscription.objects.get(pk=sub.pk)
        self.assertEqual(fresh.ends_at, before + timedelta(days=10))

    # ── invalid days ──────────────────────────────────────────────────────────
    def test_days_zero_rejected(self):
        sub = self._active_sub()
        with self.assertRaises(ValidationError):
            self.svc.extend_subscription(sub, days=0)

    def test_days_negative_rejected(self):
        sub = self._active_sub()
        with self.assertRaises(ValidationError):
            self.svc.extend_subscription(sub, days=-5)

    def test_days_non_integer_rejected(self):
        sub = self._active_sub()
        with self.assertRaises(ValidationError):
            self.svc.extend_subscription(sub, days="10")

    def test_days_bool_rejected(self):
        sub = self._active_sub()
        with self.assertRaises(ValidationError):
            self.svc.extend_subscription(sub, days=True)

    # ── invalid status ────────────────────────────────────────────────────────
    def test_expired_rejected(self):
        sub = self._sub_in_status(SubscriptionStatus.EXPIRED)
        with self.assertRaises(SubscriptionNotExtendable):
            self.svc.extend_subscription(sub, days=5)

    def test_canceled_rejected(self):
        sub = self._sub_in_status(SubscriptionStatus.CANCELED)
        with self.assertRaises(SubscriptionNotExtendable):
            self.svc.extend_subscription(sub, days=5)

    def test_payment_failed_rejected(self):
        sub = self._sub_in_status(SubscriptionStatus.PAYMENT_FAILED)
        with self.assertRaises(SubscriptionNotExtendable):
            self.svc.extend_subscription(sub, days=5)

    def test_pending_payment_rejected(self):
        sub = self.svc.create_pending_paid_subscription(self.org, self.business)
        with self.assertRaises(SubscriptionNotExtendable):
            self.svc.extend_subscription(sub, days=5)

    def test_missing_ends_at_rejected(self):
        sub = self._active_sub()
        OrganizationSubscription.objects.filter(pk=sub.pk).update(ends_at=None)
        sub.refresh_from_db()
        with self.assertRaises(SubscriptionNotExtendable):
            self.svc.extend_subscription(sub, days=5)

    # ── immutability of everything except ends_at ─────────────────────────────
    def test_only_ends_at_changes(self):
        sub = self._active_sub()
        snap = {
            "plan_id": sub.plan_id,
            "status": sub.status,
            "starts_at": sub.starts_at,
            "invoice_limit": sub.invoice_limit,
            "used_invoices": sub.used_invoices,
            "reserved_invoices": sub.reserved_invoices,
            "payment_transaction_id": sub.payment_transaction_id,
        }
        self.svc.extend_subscription(sub, days=20)
        fresh = OrganizationSubscription.objects.get(pk=sub.pk)
        self.assertEqual(fresh.plan_id, snap["plan_id"])
        self.assertEqual(fresh.status, snap["status"])
        self.assertEqual(fresh.starts_at, snap["starts_at"])
        self.assertEqual(fresh.invoice_limit, snap["invoice_limit"])
        self.assertEqual(fresh.used_invoices, snap["used_invoices"])
        self.assertEqual(fresh.reserved_invoices, snap["reserved_invoices"])
        self.assertEqual(fresh.payment_transaction_id, snap["payment_transaction_id"])

    def test_no_payment_transaction_created(self):
        sub = self._active_sub()
        before = PaymentTransaction.objects.count()
        self.svc.extend_subscription(sub, days=5)
        self.assertEqual(PaymentTransaction.objects.count(), before)

    def test_rejected_extend_does_not_change_ends_at(self):
        sub = self._sub_in_status(SubscriptionStatus.EXPIRED)
        before = sub.ends_at
        with self.assertRaises(SubscriptionNotExtendable):
            self.svc.extend_subscription(sub, days=30)
        fresh = OrganizationSubscription.objects.get(pk=sub.pk)
        self.assertEqual(fresh.ends_at, before)

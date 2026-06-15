# CRM-1F-3B-1 — Manual Payment Provider + Official Payment Service

## Summary
Adds the **payments-layer foundation** for manual (offline / bank-transfer)
payments: a new `PaymentProvider.MANUAL` choice and an official
`PaymentService.create_manual_payment()` that records a **PENDING** payment for a
pending subscription — with **no gateway, no signal, no activation**. No CRM UI,
no confirm/reject, no new model. Confirmation is deferred to a later step.

## Why provider `manual`
Keeping manual payments as `PaymentTransaction` rows with `provider="manual"`
keeps all payments in one table (unified reporting) and reuses the existing
status machine, `PaymentLog`, and — crucially — the existing
`payment_paid → subscription activation` signal chain when the payment is later
confirmed via `mark_paid`.

## Why not a hosted provider (moyasar/tap/telr)
Reusing a real provider for offline money would corrupt financial reporting (a
bank transfer shown as "Moyasar"), risk collisions with that provider's real
webhooks, and break the audit trail. Rejected.

## Why not a separate `ManualPayment` model
A separate model would duplicate the payment status machine + `PaymentLog` and
**break the activation signal chain** (which is keyed on `PaymentTransaction` +
`payment_paid`), forcing a hand-rolled activation. Rejected per the CRM-1F-3A
decision.

## Migration note
`apps/payments/migrations/0004_alter_paymenttransaction_provider.py` — a single
`AlterField` that only adds `'manual'` to the `provider` field's **choices**
(`max_length=16` unchanged). Choices are not enforced at the DB level, so this is
a **metadata-only** migration — no schema change, no data change, no new fields.

## `create_manual_payment` design
```python
PaymentService().create_manual_payment(
    *, organization, user, subscription, amount, currency,
    reference, reason=None, request=None,
) -> PaymentTransaction
```
Creates the `PaymentTransaction` **directly** (not via `create_transaction`, which
always calls the gateway + pricing). Sets: `provider=manual`, `status=pending`,
`purpose=subscription`, `reference_type=organization_subscription`,
`reference_id=subscription.id`, `amount=plan.price`, `currency=plan.currency`,
`provider_reference=reference`, `idempotency_key=manual-sub-<id>`. Writes a
`PaymentLog` (`event_type="manual_created"`). Leaves
`raw_request/raw_response/raw_webhook/checkout_url/provider_payment_id` empty.
**Does not** call a gateway, emit a signal, change `subscription.status`, or
activate anything.

## Double-active guard
To prevent a later `mark_paid` from producing two active subscriptions, the
service requires:
1. `subscription.organization_id == organization.id`;
2. `subscription.status == PENDING_PAYMENT` (active/trialing/expired/canceled/
   payment_failed are rejected);
3. the org has **no other** `active`/`trialing` subscription;
4. `amount == plan.price`, `currency == plan.currency`, `reference` non-empty.

## Idempotency behavior
`idempotency_key = "manual-sub-<subscription_id>"` → **one manual payment per
subscription**. A second `create_manual_payment` for the same subscription is
**rejected** with `PaymentValidationError` (no duplicate row, no silent return).
Because the key includes the subscription id, repeating with a different
`reference` is still rejected.

## PaymentLog behavior
A single append-only `PaymentLog` row with `event_type="manual_created"`,
`status_after="pending"`, and a payload of `{source: "crm_manual", reference,
reason, user_id}` — **no secrets** (no raw payloads, no provider ids).

## What changed
- `apps/payments/choices.py` — `PaymentProvider.MANUAL`.
- `apps/payments/migrations/0004_alter_paymenttransaction_provider.py` — choices.
- `apps/payments/services/payment_service.py` — `create_manual_payment` (+ imports).
- `apps/payments/tests/test_manual_payment.py` — new tests.

## What did NOT change
No CRM UI/forms/routes/views, no confirm/reject, no receipt upload, no
`ManualPayment` model, no webhook changes, no hosted-payment flow change
(`get_payment_gateway("manual")` still raises `ImproperlyConfigured`), no
Docker/Tailwind/frontend, no commit.

## Tests run
`apps/payments/tests/test_manual_payment.py` (19): provider exists / no gateway /
hosted intact; service creates correct pending manual txn; no secrets/gateway
fields; PaymentLog written; not activated / not paid; no gateway called; no signal
emitted; amount/currency/reference/org/status guards; other-usable guard;
duplicate rejected.
```
python manage.py check                              # 0 issues
python manage.py makemigrations --check --dry-run   # No changes (after 0004)
python -m pytest apps/payments/tests/test_manual_payment.py --no-cov -q  # 19 passed
python -m pytest apps/payments/tests/ apps/billing/tests/ apps/platform_admin/tests/ --no-cov -q  # regression
```

## Risks / Notes
- `get_payment_gateway("manual")` intentionally raises — manual must never route
  through a gateway. A test guards this.
- `paid_at` is not set here (PENDING); back-dating an actual transfer date is a
  future concern.
- The double-active guard lives in this payment service for now; if billing later
  grows a richer "renewal" flow, the guard could move/duplicate into billing.
- Amount is forced to the plan price (no partial/discount in MVP), matching hosted.

## Next step
**CRM-1F-3B-2** — CRM wrappers + UI for add/confirm/reject manual payment:
`crm_add_manual_payment` (calls `create_pending_paid_subscription` +
`create_manual_payment`), `crm_confirm_manual_payment` (calls `mark_paid` → signal
activation), `crm_reject_manual_payment` (calls `mark_canceled`), behind
`can_manage_financial_crm_data`, with AuditLog + CustomerActivity and a
Payments-tab UI.

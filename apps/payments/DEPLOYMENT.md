# Payments — Deployment Checklist

Operational items the code cannot enforce by itself. Walk this list
before flipping `PAYMENT_MODE=live`.

---

## 1. Webhook secrets — dashboard ↔ env parity

| Provider | Verification scheme            | Where to set                           | Env var                    |
|----------|--------------------------------|----------------------------------------|----------------------------|
| Moyasar  | HMAC-SHA256 of raw body        | Moyasar dashboard → Webhooks → Secret  | `MOYASAR_WEBHOOK_SECRET`   |
| Tap      | HMAC-SHA256 of raw body        | Tap dashboard → Webhooks → `hash_string` | `TAP_WEBHOOK_SECRET`     |
| Telr     | **None** (provider doesn't sign) | n/a                                  | n/a                        |

For Moyasar/Tap, the value in the env MUST match the value displayed
in the provider's dashboard exactly. A mismatch silently routes every
event into `FailedWebhookEvent` with `reason=unverified`.

Verify after deploy:

```bash
python manage.py shell -c "from apps.payments.models import FailedWebhookEvent; \
  print(FailedWebhookEvent.objects.filter(reason='unverified').count())"
```

Expected: 0 (or only your test events).

---

## 2. Telr — IP allowlist at the edge

Telr webhooks are unsigned. The adapter compensates by re-querying
`order/status` server-to-server before accepting any state change, so a
forged webhook cannot make us flip status=paid. Defence-in-depth: also
restrict `/api/v1/payments/webhooks/telr/` to Telr's egress range at
your WAF / Cloudflare / nginx layer.

Telr's outbound IPs (as of writing — verify in their docs before
applying): `185.117.81.0/24`, `185.117.83.0/24`. Whitelist by exact CIDR
in the WAF, NOT by Host header.

---

## 3. Field encryption key

```
FIELD_ENCRYPTION_KEY=<fernet key>
```

Required in non-DEBUG. Boot will fail-fast if missing. Generate with:

```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

Rotation: re-encryption requires a `manage.py rotate_field_encryption_key`
helper (not provided in this scaffold). For now: rotate by setting the
new key, then re-saving each `PaymentProviderConfig` row through the
ORM in the same process where the OLD key is still set, then deploying
the new key. Or just rotate keys at the secret-manager layer with
overlapping decryption windows.

---

## 4. HSTS, CSP, X-Frame-Options

The payment callback view is `permission_classes=[AllowAny]`. It must
remain reachable after a redirect from the gateway domain. Verify
your global response headers (`SecurityMiddleware` or similar) do not
break this:

- `Content-Security-Policy: frame-ancestors 'self'` is fine for redirect
  flows (no iframe).
- If you ever move to embedded checkout iframes, you'll need
  `frame-ancestors 'self' https://checkout.moyasar.com https://secure.tap.company`
  (and similar for Telr).
- `Strict-Transport-Security` is mandatory in production. Providers
  refuse to deliver webhooks over plain HTTP.

---

## 5. Live-mode smoke test (pre-flight)

Before opening to customers:

1. Set `PAYMENT_MODE=live`, install live keys.
2. From a real test organisation, call `POST /api/v1/payments/create/`
   with `amount=1.00 SAR` and `purpose=other`.
3. Complete the redirect with a real card you control.
4. Confirm: webhook arrived (check `PaymentLog` for `webhook_received`),
   transaction is `paid`, `provider_payment_id` matches the one shown
   in the provider's dashboard.
5. `POST /api/v1/payments/<id>/refund/` — verify a full refund completes
   and the transaction transitions to `refunded`.
6. Roll back to `PAYMENT_MODE=test` until launch.

---

## 6. Reconciliation cron

`payments.reconcile_stale_payments` runs every 10 minutes via Celery
beat. Verify the beat worker is running in production:

```bash
celery -A finai_backend inspect scheduled | grep payments
```

If beat is down, transactions stuck mid-flow (user closed tab + webhook
lost) will never recover. This task does not need a web request to
work — it talks to providers directly.

---

## 7. Replay procedure for failed webhooks

After fixing whatever caused failures (typo'd webhook secret, wrong
env, etc.):

1. Open Django admin → Payments → Failed Webhook Events.
2. Filter by `provider` and `reason` to scope to the affected batch.
3. Select rows → run the **"Replay selected webhooks through
   process_webhook"** action.
4. Successful replays mark the row `replayed=True`. Failures remain
   `replayed=False` for another attempt.

Note: replay re-runs the full pipeline including signature verify, so
the env must hold the correct secret at replay time.

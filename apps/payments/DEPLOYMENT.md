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

### Strict provider mode

`PAYMENT_STRICT_WEBHOOK_PROVIDER=true` (default) rejects webhooks
addressed to any provider other than `PAYMENT_PROVIDER` with HTTP 404.
This is the right default in steady state: stale signing keys on
unused provider URLs are an attack surface.

During a provider switch:
1. Keep the OLD provider URL active by setting
   `PAYMENT_STRICT_WEBHOOK_PROVIDER=false` (loose mode).
2. Flip `PAYMENT_PROVIDER` to the NEW provider.
3. Wait for all in-flight OLD-provider transactions to settle (use
   the `payments.reconcile_stale_payments` beat task to drain).
4. Flip `PAYMENT_STRICT_WEBHOOK_PROVIDER=true` once drained.

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

### Rotating `FIELD_ENCRYPTION_KEY`

Fernet ciphertext is keyed by the Fernet key that produced it. A key
change without re-encryption silently bricks every `secret_key` row.
The safe procedure uses Fernet's built-in **multi-key** support
implicitly via a deliberate two-step rollout:

**Procedure — zero-downtime rotation**

1. **Generate the new key** on a trusted machine:

   ```bash
   python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
   ```

2. **Stage A — re-encrypt under the OLD key process**

   Keep `FIELD_ENCRYPTION_KEY=<old_key>` in the active deployment.
   Open a `manage.py shell` with the OLD key still loaded, then
   re-save each row through the ORM so the field decrypts under the
   OLD key and re-encrypts under whatever key is current:

   ```python
   from apps.payments.models import PaymentProviderConfig
   from django.db import transaction
   with transaction.atomic():
       for cfg in PaymentProviderConfig.objects.all():
           plain = cfg.secret_key                       # decrypts under OLD
           cfg.secret_key = plain                       # re-encrypts on save
           cfg.save(update_fields=["secret_key", "updated_at"])
   ```

   At this point every row is still encrypted under the OLD key, but
   you've proven the round-trip works.

3. **Stage B — flip the key**

   Roll out a new release with `FIELD_ENCRYPTION_KEY=<new_key>`. As
   soon as it boots, every `secret_key` read will fail (`InvalidToken`
   silently swallowed → returns `""` per
   `EncryptedTextField._decrypt`). So **do not** flip the key alone.

4. **Stage B' — combined cutover**

   Instead: in a single deploy window, perform stages A and B
   together while the application is paused (or accept a brief
   outage):

   ```bash
   # 1. Take the worker offline (so no payment can fire mid-rotation).
   systemctl stop tadgeeg-celery
   # 2. Re-encrypt under the new key using BOTH keys side by side.
   FIELD_ENCRYPTION_KEY=$NEW_KEY \
   LEGACY_FIELD_ENCRYPTION_KEY=$OLD_KEY \
       python manage.py rotate_field_encryption_key   # see below
   # 3. Restart workers + web with the new key only.
   ```

5. **One-shot rotation helper** *(not shipped — add when needed)*

   Implementation sketch in `apps/payments/management/commands/
   rotate_field_encryption_key.py`:

   ```python
   from cryptography.fernet import Fernet, MultiFernet
   new = Fernet(os.environ["FIELD_ENCRYPTION_KEY"])
   old = Fernet(os.environ["LEGACY_FIELD_ENCRYPTION_KEY"])
   fernet = MultiFernet([new, old])     # decrypt with either, encrypt with new
   for cfg in PaymentProviderConfig.objects.all():
       raw = cfg._meta.get_field("secret_key").value_from_object(cfg)
       plain = fernet.decrypt(raw.encode("utf-8")).decode("utf-8")
       cfg.secret_key = plain
       cfg.save(update_fields=["secret_key", "updated_at"])
   ```

   Build that command on first rotation.

**Alternative — secret manager with overlapping windows**

If you front the key with AWS Secrets Manager / GCP Secret Manager /
Vault, the manager handles rotation natively: keep two versions
active during the cutover window, instruct the app to read the
"current" version, and retire the old version once you've confirmed
no ciphertext still references it.

**Verification after rotation**

```python
# manage.py shell
from apps.payments.models import PaymentProviderConfig
broken = sum(1 for cfg in PaymentProviderConfig.objects.all() if not cfg.secret_key)
assert broken == 0, f"{broken} configs failed to decrypt — abort the rotation"
```

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

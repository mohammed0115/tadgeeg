# ADR 0006 — Plan limit dimensions, and why `company_limit` is not built

- **Status:** Accepted. One dimension deliberately **not** implemented.
- **Date:** 2026-07-30
- **Phase:** 3A

## Where limits actually live

Investigated before designing, because the answer determines everything else.

**Both.** The catalogue holds the *offer*; the subscription holds the *contract*:

| Layer | Field | Role |
|---|---|---|
| `billing.Plan` | `invoice_limit`, `user_limit` | what the plan currently offers |
| `billing.OrganizationSubscription` | `invoice_limit`, `user_limit` | what THIS customer was sold |

The subscription snapshots the plan at creation
(`subscription_service.py:71, :107`) and again at activation (`:165`).
Enforcement (`QuotaService`) reads the **subscription**, never the plan.

That separation is what lets a catalogue edit change the offer without
repricing or re-limiting anyone already paying. It is the mechanism behind
MONEY RULE 1, it already existed, and Phase 3A preserved it rather than
inventing anything.

> The Phase 3A prompt stated that `Plan` had "no limit fields at all". That is
> incorrect — `Plan.invoice_limit` has existed since the initial billing
> migration (`apps/billing/models.py:51`). Had it been true, the whole design
> below would have needed a different shape, which is exactly why the prompt
> asked for the investigation first.

## Conventions

**`None` means unlimited. `0` means no allowance.** These are opposites and
must never be conflated. `0` was already meaningful on these columns, so
overloading it would make an Enterprise plan indistinguishable from a disabled
one. `Plan.has_limit()` is the single place the convention is interpreted;
enforcement calls it rather than open-coding `is not None`, and never compares
against a sentinel large number.

**`price = None` + `is_custom_quote = True` means contact sales.** Not `0.00`,
which reads as *free* and would let an unlimited plan be bought through
self-service checkout for nothing. Refusal is server-side in
`SelectPlanView` (409 `contact_sales`), not merely hidden in the UI.

Making `price` nullable put a `None` into three existing
`Decimal(plan.price)` call sites, none of which had a guard:
`SubscriptionService.create_pending_paid_subscription`,
`PaymentService.create_manual_payment` (`payment_service.py:250`) and
`pricing._subscription_resolver` (`pricing.py:139`). Each now refuses in its own
layer with a priced-refusal error instead of raising `TypeError` as a 500.

**Consequence, stated plainly: an Enterprise plan currently cannot be sold.**
Self-service refuses it by design, and the staff manual-payment path insists the
recorded amount equal the (nonexistent) list price. Recording a negotiated deal
needs the agreed price stored on the subscription — the same missing column
described below. Until that lands, Enterprise is a *lead-generation* listing, not
a purchasable plan. That is a clean refusal rather than a crash, which is the
improvement Phase 3A delivers here; it is not a complete sales path.

## `user_limit` — built

Modelled on the invoice dimension rather than as a second mechanism. The one
real difference: seats are a **live count** of the organisation's active users,
not a consumed-and-ledgered allowance, so there is nothing to reserve or
release and no `UsageLedger` rows are written. Counting happens in SQL.

Enforced in `SeatService`, called from the user-creation API. The error names
*which* limit was hit — "user limit", not a bare "limit exceeded", because a
caller cannot otherwise tell seats from invoices.

Platform staff bypass: support must be able to fix an account regardless of its
plan.

### The snapshot had a hole, and adding a dimension exposed it

The snapshot mechanism above was written for one dimension. All three creation
paths in `SubscriptionService` — `create_free_trial`,
`create_pending_paid_subscription`, `activate_subscription` — froze
`invoice_limit` and nothing else. Adding `user_limit` to the models did **not**
make it get written: every real subscription kept `user_limit = NULL`, which
this codebase reads as *unlimited*.

So seat enforcement passed its unit tests (they set the column directly) and was
dead for every actual customer. Fixed by freezing both dimensions at all three
sites; `apps/billing/tests/test_limit_snapshot.py` goes through the real service
path specifically so a hand-set column cannot fake it again.

The general rule this produced: **a limit dimension is not "built" until a path
that a customer can actually reach writes it.** A column plus an enforcement
function is half a feature.

Existing rows are deliberately left at `NULL`. They were sold without a seat cap
and MONEY RULE 1 says they keep what they were sold — so no data migration.

### Price is *not* snapshotted — a real gap, reported not silently patched

`OrganizationSubscription` freezes limits but has no `price_at_purchase`.
Payment amounts resolve from the **live** plan
(`apps/payments/pricing.py:148`, `payment_service.py:256`). A catalogue price
edit therefore changes what a pending subscription will be charged.

This predates Phase 3A and fixing it means a new column plus a decision about
in-flight subscriptions, so it is reported rather than changed here. It is the
top blocker for 3B, and it is also why custom-quote plans cannot yet be sold —
see below.

## `company_limit` — NOT built. This is a finding, not an omission.

§J prices accounting-firm plans on a company dimension: 20 / 50 / unlimited
client companies under one subscription.

**The current architecture cannot express that.** Evidence:

| Fact | Location |
|---|---|
| A subscription belongs to exactly ONE organization | `billing/models.py:128` — `organization = FK(Organization)` |
| Only one usable subscription per organization | `billing/models.py:183` — `UniqueConstraint(fields=["organization"], condition=status in (active, trialing))` |
| A user belongs to exactly ONE organization | `authentication/models.py:137` |
| No parent/child or managed-company relation exists | grep for `parent` / `managed_by` / `owner_organization` across `apps/authentication` and `apps/billing` → no matches |

So "one accounting firm, one subscription, twenty client companies" has no
representation. Supporting it needs either a `ManagedCompany` entity beneath
`Organization`, or a parent/child relation between organizations, or
multi-organization membership for users. Each rewrites the tenant boundary that
**every** `organization=`-scoped query in the product depends on.

That is a Phase 4-sized architectural decision. Inventing it as a side effect of
a pricing change would be the wrong way to make it.

**Consequently the field is not added and the number is not stored.** Storing
`company_limit = 20` while nothing can enforce it would be a documented
guarantee that does not exist — the exact failure mode Phase 2B shipped once
and caught.

The accounting plans are still seeded, with their real prices, seat limits and
invoice limits. Only the company dimension is absent.

**What the product owner needs to decide before Phase 4:** whether an
accounting firm's client companies are (a) full tenants with their own data
isolation, (b) sub-entities inside one tenant, or (c) something the firm
manages externally with the platform seeing only aggregate volume. The three
have very different costs, and (a) is the expensive one.

## Consequences

- A catalogue edit is safe for existing subscribers by construction, and
  `tests/test_plan_catalogue.py` asserts it.
- Adding a third limit dimension later means: a column on both models, a branch
  in enforcement, and a seed value — the pattern is now established twice.
- Accounting plans are sellable but do not deliver the multi-company capability
  the spec describes. **Sales must not promise it until Phase 4 lands.** That is
  the operational consequence of this ADR and the reason it is written down.

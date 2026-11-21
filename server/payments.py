"""Stripe web payments via hosted Checkout, for the subscription tiers.

Env-driven, so no keys ever live in the repo:
  JOBCAST_STRIPE_SECRET_KEY        - sk_test_... / sk_live_...
  JOBCAST_STRIPE_PUBLISHABLE_KEY   - pk_test_... (not strictly needed for hosted Checkout)
  JOBCAST_STRIPE_WEBHOOK_SECRET    - whsec_... (verifies webhook calls)
  JOBCAST_STRIPE_PRICE_TIER{1,2,3}_{MONTHLY,YEARLY} - the Stripe Price IDs

Degrades gracefully: with no secret key, configured() is False and the app keeps its
free/preview behaviour (clicking a plan just generates the plan, nothing is charged)."""

import os
import sys
import json
import time
import secrets
from pathlib import Path

# Persist on the mounted disk in production (auto-detected), so subscriber records
# survive deploys; falls back to the repo data dir for local dev.
from .datadir import data_dir as _data_dir
SUBS_FILE = _data_dir() / "subscriptions.jsonl"

TIER_RANK = {"free": 0, "tier1": 1, "tier2": 2, "tier3": 3}

# (tier, period) -> env var holding that plan's Stripe Price ID
PRICE_ENV = {
    ("tier1", "monthly"): "JOBCAST_STRIPE_PRICE_TIER1_MONTHLY",
    ("tier1", "yearly"): "JOBCAST_STRIPE_PRICE_TIER1_YEARLY",
    ("tier2", "monthly"): "JOBCAST_STRIPE_PRICE_TIER2_MONTHLY",
    ("tier2", "yearly"): "JOBCAST_STRIPE_PRICE_TIER2_YEARLY",
    ("tier3", "monthly"): "JOBCAST_STRIPE_PRICE_TIER3_MONTHLY",
    ("tier3", "yearly"): "JOBCAST_STRIPE_PRICE_TIER3_YEARLY",
}

# Prices in cents, set right here via inline price_data - change the number to change the
# price, no Stripe dashboard step needed. (tier2 = the "Monitor" plan.)
PRICE_CENTS = {
    ("tier2", "once"): 499,       # $4.99 one-time (full plan, no subscription)
    ("tier2", "monthly"): 199,    # $1.99 / month
    ("tier2", "yearly"): 1200,    # $12 / year  (~$1/mo)
}


def _secret():
    return os.environ.get("JOBCAST_STRIPE_SECRET_KEY")


def configured():
    return bool(_secret())


def publishable_key():
    return os.environ.get("JOBCAST_STRIPE_PUBLISHABLE_KEY", "")


def _client():
    import stripe
    stripe.api_key = _secret()
    return stripe


def price_id(tier, period):
    env = PRICE_ENV.get((tier, period))
    return os.environ.get(env) if env else None


def create_checkout_session(tier, period, success_url, cancel_url, email=None, ref=None):
    """Return (session, None) on success or (None, error_code). The price is set inline
    (price_data from PRICE_CENTS), so it can be changed in code with no Stripe dashboard
    step. Entitlement is carried by metadata, not the price id."""
    cents = PRICE_CENTS.get((tier, period))
    if not cents:
        return None, "price_not_configured"
    onetime = (period == "once")
    price_data = {
        "currency": "usd",
        "unit_amount": cents,
        "product_data": {"name": "JobBreak full plan" if onetime else "JobBreak Monitor"},
    }
    if not onetime:
        price_data["recurring"] = {"interval": "year" if period == "yearly" else "month"}
    try:
        stripe = _client()
        session = stripe.checkout.Session.create(
            mode="payment" if onetime else "subscription",
            line_items=[{"price_data": price_data, "quantity": 1}],
            success_url=success_url,
            cancel_url=cancel_url,
            allow_promotion_codes=True,
            customer_email=email or None,
            metadata={"tier": tier, "period": period,
                      **({"ref": ref} if ref else {})},
        )
        return session, None
    except Exception as e:
        print(f"[payments] checkout create failed: {type(e).__name__}: {e}", file=sys.stderr, flush=True)
        return None, "stripe_error"


def create_reward_promo_code(percent=50):
    """Create a one-time percent-off coupon plus a single-use promotion code, for a
    referral reward. Returns (code, None) or (None, error). Customers redeem it at
    checkout, which already has allow_promotion_codes=True."""
    try:
        stripe = _client()
        coupon = stripe.Coupon.create(percent_off=percent, duration="once",
                                       name="JobBreak referral reward")
        code = "REF" + secrets.token_hex(3).upper()
        promo = stripe.PromotionCode.create(coupon=coupon.id, code=code, max_redemptions=1)
        return _get(promo, "code") or code, None
    except Exception as e:
        print(f"[payments] reward promo create failed: {type(e).__name__}: {e}", file=sys.stderr, flush=True)
        return None, "stripe_error"


def retrieve_session(session_id):
    try:
        return _client().checkout.Session.retrieve(session_id, expand=["line_items"])
    except Exception as e:
        print(f"[payments] session retrieve failed: {e}", file=sys.stderr, flush=True)
        return None


def _get(obj, key):
    if obj is None:
        return None
    if isinstance(obj, dict):
        return obj.get(key)
    return getattr(obj, key, None)


def _tier_for_price(pid):
    if not pid:
        return None
    for (tier, _period), env in PRICE_ENV.items():
        if os.environ.get(env) == pid:
            return tier
    return None


def _sole_paid_tier():
    """The highest-rank tier that actually has a price for sale. A completed, paid checkout
    can only have bought a tier we sell, so this is the safe fallback when a session's
    metadata is missing (the inline-price path leaves no price id to match). Today only
    tier2 (Monitor) has prices, so this returns 'tier2'."""
    tiers = {t for (t, _period) in PRICE_CENTS.keys()}
    return max(tiers, key=lambda t: TIER_RANK.get(t, 0)) if tiers else None


def tier_from_session(session):
    """The advice tier a completed checkout grants, or None. Robust to subscription mode
    (which signals completion via status == 'complete') and to missing metadata: a session
    that is genuinely complete/paid but carries no tier falls back to the only paid tier on
    sale, so a real payment is never left locked out over a metadata gap."""
    if not session:
        return None
    status = _get(session, "status")
    pstatus = _get(session, "payment_status")
    md = _get(session, "metadata") or {}
    tier = md.get("tier") if hasattr(md, "get") else None
    if not tier:
        try:
            items = _get(_get(session, "line_items"), "data") or []
            for it in items:
                tier = _tier_for_price(_get(_get(it, "price"), "id"))
                if tier:
                    break
        except Exception:
            pass
    done = (status == "complete") or (pstatus in ("paid", "no_payment_required"))
    if not tier and done:
        # A genuinely paid checkout with no resolvable tier (inline prices leave no price id
        # to match, and metadata can be absent). Grant the only paid tier rather than leave a
        # paying customer stuck on "processing".
        tier = _sole_paid_tier()
    print(f"[payments] success session tier={tier} status={status} payment_status={pstatus}",
          file=sys.stderr, flush=True)
    if done and tier in TIER_RANK and tier != "free":
        return tier
    return None


# --- Durable, race-free unlock: session_id -> granted tier ------------------------------
# The checkout.session.completed webhook fires server-side and never races the browser
# redirect, so it records the grant here; /billing/success reads it first. Append-only so
# concurrent writes (webhook + success page) can't corrupt it, and grants are idempotent.
GRANTS_FILE = _data_dir() / "grants.jsonl"


def record_grant(session_id, tier):
    if not session_id or not tier:
        return
    try:
        GRANTS_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(GRANTS_FILE, "a", encoding="utf-8") as fh:
            fh.write(json.dumps({"sid": session_id, "tier": tier, "ts": int(time.time())}) + "\n")
    except Exception:
        pass


def grant_for(session_id):
    """The tier recorded for this checkout session, or None. Last write wins."""
    if not session_id or not GRANTS_FILE.exists():
        return None
    found = None
    try:
        with open(GRANTS_FILE, encoding="utf-8") as fh:
            for line in fh:
                try:
                    rec = json.loads(line)
                except Exception:
                    continue
                if rec.get("sid") == session_id and rec.get("tier"):
                    found = rec["tier"]
    except Exception:
        return None
    return found


def verify_webhook(payload, sig_header):
    """Construct a verified Stripe event. Falls back to unverified parse only when no
    webhook signing secret is set (local dev)."""
    secret = os.environ.get("JOBCAST_STRIPE_WEBHOOK_SECRET")
    if secret:
        return _client().Webhook.construct_event(payload, sig_header, secret)
    return json.loads(payload)


def record_subscription(rec):
    try:
        SUBS_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(SUBS_FILE, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(rec) + "\n")
    except Exception:
        pass


# --- Customer-service helpers -----------------------------------------------------------
# All keyed off a Stripe Checkout Session id, which the customer has from their receipt / the
# billing-success URL and which is hard to guess, so it doubles as proof of ownership for the
# self-serve paths. The money actions (refund, cancel) are only ever called from the
# admin-key-gated routes.

def valid_session_id(session_id):
    """A plausible Stripe Checkout Session id (cs_test_... / cs_live_...). Cheap guard so a
    bad paste never reaches the Stripe API or an open redirect."""
    sid = (session_id or "").strip()
    return bool(sid) and sid.startswith("cs_") and len(sid) <= 120 and sid.replace("_", "").isalnum()


def email_for_session(session_id):
    """The email on a checkout session (customer_details.email), best-effort, or None."""
    sess = retrieve_session(session_id)
    details = _get(sess, "customer_details") or {}
    return details.get("email") if hasattr(details, "get") else None


def refund_session(session_id):
    """Refund the payment behind a checkout session. Returns (refund, None) or (None, err).
    Works for the one-time plan and for a subscription's latest invoice payment."""
    try:
        stripe = _client()
        sess = stripe.checkout.Session.retrieve(session_id)
        pi = _get(sess, "payment_intent")
        if not pi:
            # Subscription checkouts carry no top-level payment_intent; refund the latest
            # invoice's charge instead.
            sub = _get(sess, "subscription")
            if sub:
                s = stripe.Subscription.retrieve(sub, expand=["latest_invoice"])
                inv = _get(s, "latest_invoice") or {}
                pi = _get(inv, "payment_intent")
        if not pi:
            return None, "no_payment"
        refund = stripe.Refund.create(payment_intent=pi if isinstance(pi, str) else _get(pi, "id"))
        return refund, None
    except Exception as e:
        print(f"[payments] refund failed: {type(e).__name__}: {e}", file=sys.stderr, flush=True)
        return None, "stripe_error"


def cancel_subscription_for(session_id, at_period_end=True):
    """Cancel the subscription attached to a checkout session. Returns (sub, None) or
    (None, err). at_period_end keeps access until the paid period ends (the kind default);
    pass False for an immediate cancel."""
    try:
        stripe = _client()
        sess = stripe.checkout.Session.retrieve(session_id)
        sub = _get(sess, "subscription")
        if not sub:
            return None, "no_subscription"
        if at_period_end:
            updated = stripe.Subscription.modify(sub, cancel_at_period_end=True)
        else:
            updated = stripe.Subscription.cancel(sub)
        return updated, None
    except Exception as e:
        print(f"[payments] cancel failed: {type(e).__name__}: {e}", file=sys.stderr, flush=True)
        return None, "stripe_error"


def billing_portal_url(session_id, return_url):
    """A Stripe-hosted customer-portal URL for the customer behind a checkout session, where
    they can cancel, update their card, and see invoices. Returns (url, None) or (None, err).
    err 'no_customer' means a one-time purchase (no subscription to manage). The portal must
    be enabled once in Stripe -> Settings -> Billing -> Customer portal, else 'stripe_error'."""
    try:
        stripe = _client()
        sess = stripe.checkout.Session.retrieve(session_id)
        cust = _get(sess, "customer")
        if not cust:
            return None, "no_customer"
        ps = stripe.billing_portal.Session.create(customer=cust, return_url=return_url)
        return _get(ps, "url"), None
    except Exception as e:
        print(f"[payments] portal failed: {type(e).__name__}: {e}", file=sys.stderr, flush=True)
        return None, "stripe_error"


def receipt_for_session(session_id):
    """(receipt_url, email) for a checkout session's charge, best-effort; either may be None.
    Used to re-send a receipt."""
    try:
        stripe = _client()
        sess = stripe.checkout.Session.retrieve(session_id)
        details = _get(sess, "customer_details") or {}
        email = details.get("email") if hasattr(details, "get") else None
        pi = _get(sess, "payment_intent")
        if not pi:
            sub = _get(sess, "subscription")
            if sub:
                s = stripe.Subscription.retrieve(sub, expand=["latest_invoice"])
                inv = _get(s, "latest_invoice") or {}
                url = _get(inv, "hosted_invoice_url")
                if url:
                    return url, email
                pi = _get(inv, "payment_intent")
        pid = pi if isinstance(pi, str) else _get(pi, "id")
        if pid:
            pio = stripe.PaymentIntent.retrieve(pid)
            charge_id = _get(pio, "latest_charge")
            if charge_id:
                ch = stripe.Charge.retrieve(charge_id if isinstance(charge_id, str) else _get(charge_id, "id"))
                return _get(ch, "receipt_url"), (email or _get(ch, "receipt_email"))
        return None, email
    except Exception as e:
        print(f"[payments] receipt lookup failed: {type(e).__name__}: {e}", file=sys.stderr, flush=True)
        return None, None


def lookup(query):
    """Admin lookup: find the Stripe checkout session for a session id OR an email. Returns a
    plain dict of the fields the admin tool shows, or {'error': ...}. Email search scans the
    recent sessions list (most recent match wins)."""
    q = (query or "").strip()
    if not q:
        return {"error": "empty"}
    try:
        stripe = _client()
        sess = None
        if q.startswith("cs_"):
            sess = stripe.checkout.Session.retrieve(q, expand=["line_items"])
        else:
            # treat as email; scan recent sessions
            ql = q.lower()
            for s in stripe.checkout.Session.list(limit=50).auto_paging_iter():
                det = _get(s, "customer_details") or {}
                em = (det.get("email") if hasattr(det, "get") else None) or ""
                if em.lower() == ql:
                    sess = stripe.checkout.Session.retrieve(_get(s, "id"), expand=["line_items"])
                    break
        if not sess:
            return {"error": "not_found"}
        details = _get(sess, "customer_details") or {}
        md = _get(sess, "metadata") or {}
        created = _get(sess, "created")
        amt = _get(sess, "amount_total")
        return {
            "id": _get(sess, "id"),
            "email": details.get("email") if hasattr(details, "get") else None,
            "mode": _get(sess, "mode"),
            "status": _get(sess, "status"),
            "payment_status": _get(sess, "payment_status"),
            "customer": _get(sess, "customer"),
            "subscription": _get(sess, "subscription"),
            "tier": (md.get("tier") if hasattr(md, "get") else None),
            "period": (md.get("period") if hasattr(md, "get") else None),
            "grants": tier_from_session(sess),
            "amount": (round(amt / 100.0, 2) if amt else None),
            "currency": (_get(sess, "currency") or "usd").upper(),
            "created": (time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime(created)) if created else None),
        }
    except Exception as e:
        print(f"[payments] lookup failed: {type(e).__name__}: {e}", file=sys.stderr, flush=True)
        return {"error": "stripe_error"}

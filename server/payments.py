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


def create_checkout_session(tier, period, success_url, cancel_url, email=None):
    """Return (session, None) on success or (None, error_code)."""
    pid = price_id(tier, period)
    if not pid:
        return None, "price_not_configured"
    try:
        stripe = _client()
        session = stripe.checkout.Session.create(
            mode="subscription",
            line_items=[{"price": pid, "quantity": 1}],
            success_url=success_url,
            cancel_url=cancel_url,
            allow_promotion_codes=True,
            customer_email=email or None,
            metadata={"tier": tier, "period": period},
        )
        return session, None
    except Exception as e:
        print(f"[payments] checkout create failed: {type(e).__name__}: {e}", file=sys.stderr, flush=True)
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


def tier_from_session(session):
    """The advice tier a completed checkout grants, or None. Robust to subscription mode
    (which signals completion via status == 'complete') and to missing metadata (falls back
    to the purchased price)."""
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
    print(f"[payments] success session tier={tier} status={status} payment_status={pstatus}",
          file=sys.stderr, flush=True)
    done = (status == "complete") or (pstatus in ("paid", "no_payment_required"))
    if done and tier in TIER_RANK and tier != "free":
        return tier
    return None


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

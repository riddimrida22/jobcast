# Payments (Stripe) setup

Web payments use Stripe hosted Checkout. Card details never touch this server; the keys
live only in environment variables, never in the repo. With no keys set, the app keeps its
free/preview behaviour (clicking a plan just generates a plan, nothing is charged).

The mobile apps will NOT use Stripe: Apple and Google require in-app purchases for digital
subscriptions. Plan to add RevenueCat + Apple IAP + Google Play Billing when the apps ship.

## One-time setup (test mode first)

1. Create a Stripe account and stay in **Test mode** (toggle, top-right of the dashboard).

2. Copy your test keys from Developers -> API keys:
   - Secret key `sk_test_...`
   - Publishable key `pk_test_...`

3. Create the products and prices. From the repo root, with the stripe lib installed
   (`pip install stripe`):

   ```bash
   JOBCAST_STRIPE_SECRET_KEY=sk_test_xxx python scripts/setup_stripe_products.py
   ```

   It prints six `JOBCAST_STRIPE_PRICE_*` lines. Keep them.

4. Set the environment variables (locally for testing, and in Render -> Environment):

   ```
   JOBCAST_STRIPE_SECRET_KEY=sk_test_xxx
   JOBCAST_STRIPE_PUBLISHABLE_KEY=pk_test_xxx
   JOBCAST_STRIPE_PRICE_TIER1_MONTHLY=price_...
   JOBCAST_STRIPE_PRICE_TIER1_YEARLY=price_...
   JOBCAST_STRIPE_PRICE_TIER2_MONTHLY=price_...
   JOBCAST_STRIPE_PRICE_TIER2_YEARLY=price_...
   JOBCAST_STRIPE_PRICE_TIER3_MONTHLY=price_...
   JOBCAST_STRIPE_PRICE_TIER3_YEARLY=price_...
   ```

5. Add the webhook. In Stripe -> Developers -> Webhooks -> Add endpoint:
   - URL: `https://YOUR-DOMAIN/webhooks/stripe`
   - Event: `checkout.session.completed`
   - Copy the signing secret `whsec_...` and set `JOBCAST_STRIPE_WEBHOOK_SECRET=whsec_...`.

## Test the flow

- With the test keys set, open a result page and click a paid plan. You are sent to Stripe
  Checkout. Pay with the test card `4242 4242 4242 4242`, any future expiry, any CVC/ZIP.
- You return to `/billing/success`, the session cookie is granted the tier, and generating
  the plan now works at that level. `/v1/advice` returns HTTP 402 for a paid tier until the
  entitlement is present.

## Go live

1. Switch the dashboard to Live mode, create live products/prices (run the script with the
   live key, or copy the prices), and get live keys + a live webhook secret.
2. Replace every `sk_test_/pk_test_/price_(test)/whsec_(test)` value with the live ones.
3. Apple/Google note: do NOT sell these subscriptions inside the iOS/Android apps with
   Stripe; use in-app purchase there (see mobile/README.md).

## How entitlement works today

Minimal, cookie-based, no user accounts yet: a completed checkout sets `jb_tier` in the
signed session cookie, and `/v1/advice` honours it. The subscription is also appended to
`data/subscriptions.jsonl` from the webhook. Before a real launch, move entitlement to
proper accounts (so a subscription survives a cleared cookie and can be managed), likely via
RevenueCat once the apps exist.

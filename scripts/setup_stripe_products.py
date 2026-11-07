"""Create the JobBreak subscription product and prices in your Stripe account, then print
the env var lines to set. Run ONCE per environment (test, then live), keep the output:

    # test:
    JOBCAST_STRIPE_SECRET_KEY=sk_test_xxx python scripts/setup_stripe_products.py
    # live (when you are ready to take real money):
    JOBCAST_STRIPE_SECRET_KEY=sk_live_xxx python scripts/setup_stripe_products.py

Amounts are in USD cents. Edit PLANS below if you change the pricing. Re-running creates
new products/prices (Stripe has no safe "upsert"), so run it once per environment."""

import os
import sys

try:
    import stripe
except ImportError:
    sys.exit("Install the Stripe library first:  pip install stripe")

key = os.environ.get("JOBCAST_STRIPE_SECRET_KEY")
if not key:
    sys.exit("Set JOBCAST_STRIPE_SECRET_KEY to your sk_test_... or sk_live_... key and re-run.")
mode = "LIVE" if key.startswith("sk_live_") else "TEST"
print("Running in %s mode.\n" % mode)
stripe.api_key = key

# tier, display name, monthly cents, yearly cents
# The single "JobBreak Monitor" plan maps to tier2 in the app ($3.99/mo, $29/yr).
PLANS = [
    ("tier2", "Monitor", 399, 2900),
]

env_lines = []
for tier, name, monthly_cents, yearly_cents in PLANS:
    product = stripe.Product.create(name="JobBreak " + name)
    m = stripe.Price.create(product=product.id, unit_amount=monthly_cents, currency="usd",
                            recurring={"interval": "month"})
    y = stripe.Price.create(product=product.id, unit_amount=yearly_cents, currency="usd",
                            recurring={"interval": "year"})
    env_lines.append("JOBCAST_STRIPE_PRICE_%s_MONTHLY=%s" % (tier.upper(), m.id))
    env_lines.append("JOBCAST_STRIPE_PRICE_%s_YEARLY=%s" % (tier.upper(), y.id))
    print("Created %s: monthly %s, yearly %s" % (name, m.id, y.id))

print("\n--- Set these env vars (locally and in Render), plus your keys ---")
for line in env_lines:
    print(line)

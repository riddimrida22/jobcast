"""Create the JobBreak subscription products and prices in your Stripe account, then print
the env var lines to set. Run ONCE with your TEST secret key, keep the output:

    JOBCAST_STRIPE_SECRET_KEY=sk_test_xxx python scripts/setup_stripe_products.py

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
    sys.exit("Set JOBCAST_STRIPE_SECRET_KEY to your TEST key (sk_test_...) and re-run.")
if key.startswith("sk_live_"):
    sys.exit("That is a LIVE key. Use your TEST key (sk_test_...) to set up and test first.")
stripe.api_key = key

# tier, display name, monthly cents, yearly cents
PLANS = [
    ("tier1", "Starter", 500, 5000),
    ("tier2", "Pro", 1200, 12000),
    ("tier3", "Career Shield", 2900, 29000),
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

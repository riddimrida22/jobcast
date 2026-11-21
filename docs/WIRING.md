# How JobBreak is wired

A map of how the whole system connects, written 21 Nov 2026. Emphasis on the paywall.
(Secrets are referenced by env-var NAME only, never value.)

## 1. Hosting & deploy
- **Live site:** https://jobbreak.ai  (custom domain on the Render service `jobcast-demo`).
- **Render service:** `jobcast-demo` (web service, Docker, region Ohio, id `srv-dbn7s4jbc2fs738ponq0`),
  on the **paid Starter plan ($7/mo, 0.5 CPU / 512 MB, always-on — does not sleep)**.
- **Render account:** the one tied to **bertrand_byrne@hotmail.com** (NOT the aquatechpc Google account,
  whose Render workspace is empty). Log in with hotmail to touch env vars / the instance.
- **Deploy:** push to `main` on GitHub `riddimrida22/jobcast` → Render **auto-deploys** (~40-60s, brief 502).
- **Stack:** Python / Flask, served by **gunicorn** via Dockerfile. Engine (`riskcore`) is pure stdlib.

## 2. The user journey (request flow)
1. **Home** (`GET /`, `index.html`) — hero + "type your job" box; also "most/least exposed" lists.
2. **Assess** (`POST /assess`) — wizard answers (job, location, a bit about you) → `engine.assess(profile)`
   computes the score + drivers + exposed/resilient tasks + timeline + adjacent lower-risk roles.
3. **Result** (`result.html`) — shows the **score first** (free taste), then the wall.
4. **Paywall → pay → unlock** (section 3).
5. **Paid content** — the AI advice plan (and, soon, the green-option: skills-matched safer role).

## 3. THE PAYWALL (detailed)
No user accounts. Entitlement rides on the Stripe **Checkout Session id** + a session cookie.

**a) Trigger (`result.html`).** The result page reveal is gated by `jb_reveal` (sessionStorage); the full
breakdown/advice sits behind the wall. `openUpsell` / `#rlock` / `directCheckout` (bridged by
`window.jbOpenPaywall`) all POST to `/checkout`.

**b) Create checkout (`POST /checkout`, server/__init__.py:628).** Takes `tier` (tier1/2/3) + `period`
(monthly/yearly/once). **Default buy = tier2 / once = $4.99 one-time.** Calls
`payments.create_checkout_session`, which builds a Stripe Checkout Session: price is **inline** from
`PRICE_CENTS` (so prices live in code, no Stripe dashboard step), entitlement tier carried in **metadata**,
**automatic payment methods** (so Stripe shows Apple Pay / Google Pay / Link / Cash App Pay / Card per
device — all enabled in the Stripe dashboard as of 21 Nov, Google Pay added that day). Returns the hosted
Stripe URL; the browser redirects to it.

**c) Pay (Stripe-hosted).** One-tap wallet or card. Success → redirect to
`/billing/success?session_id={CHECKOUT_SESSION_ID}`.

**d) Grant entitlement (`GET /billing/success`, :674).** Race-safe, two paths:
  1. **Webhook first:** `grant_for(sid)` — the Stripe webhook (`checkout.session.completed`, ~:798) already
     recorded the unlock server-side, so trust that.
  2. **Fallback:** retry `retrieve_session(sid)` up to 8× (0.5s) to ride out the Apple-Pay/redirect-beats-
     Stripe lag, then `tier_from_session` reads the tier from metadata.
  On success: `record_grant(sid, tier)` (persists so any later reload unlocks instantly),
  `session["jb_tier"] = tier` (the entitlement cookie), `session.permanent = True`. Also records the
  subscription and, for Monitor, arms an alert on the job the user was viewing (`jb_soc`).

**e) The bearer.** The **checkout session id (`cs_live_...`)** is the durable proof of purchase (persisted
via `record_grant`). The customer has it from their receipt / the success URL; the support module
(`/support/restore`, `/support/manage`, `/admin/support`) keys off it.

**f) Gating (`/v1/advice`, :272).** If payments are configured and the requested tier outranks the
session's `jb_tier` (`TIER_RANK`), returns **402 payment_required**. So AI advice stays locked until paid.

**g) Free vs paid content.**
  - **Free:** deterministic "rules" strategies from the engine (generic by design) — the taste that must
    create curiosity. 1 strategy.
  - **Paid (tier2 = $4.99):** AI advice via `server/advice.py` — Sonnet + live web search with citations,
    grounded in the person's real exposed tasks. (tier1=Haiku, tier3=Opus.)
  - **In progress:** the "green option" — post-pay skills capture → skill-matched safer role (own session/PR).

**h) Funnel visibility.** `POST /v1/ev` logs buy-funnel events; they appear in `/admin/stats` under
`/_ev/<name>`, so drop-off in the buy flow is measurable.

## 4. Advice engine (server/advice.py)
Turns the computed result into a plan (explanation, never scoring — the one allowed LLM use). Needs
`JOBCAST_ANTHROPIC_KEY` (CONFIRMED set in Render 21 Nov, so AI advice runs). No key → silently falls back
to the deterministic rules. Prompts ban generic filler and force grounding in the person's real tasks.

## 5. Data pipeline (ingest/)
O*NET 29.1 (tasks, work context, related occupations) + Eloundou 2023 AI-exposure + a robotics proxy +
BLS OEWS wages/employment (national + 393 metros) + live CPI. Built into `data/snapshots/`; the committed
demo copy is `data/demo/snapshot.json`. Point the app at one with `JOBCAST_SNAPSHOT`.

## 6. Support module (shipped 21 Nov, PR #2)
`/help` (`/support`) FAQ + contact form (→ support@jobbreak.ai via Resend); self-serve restore-access and
Stripe customer-portal; admin `/admin/support?key=JOBCAST_ADMIN_KEY` to look up a purchase and re-send a
receipt / re-grant / cancel / refund. All money actions admin-gated.

## 7. Analytics
First-party, cookie-free (`server/analytics_store.py` → `analytics.db` on the persistent disk). Private
dashboard `/admin/stats?key=JOBCAST_ADMIN_KEY`.

## 8. Env vars / secrets (NAMES only — set in the Render `jobcast-demo` service)
`JOBCAST_ANTHROPIC_KEY` (AI advice), Stripe keys + `STRIPE_WEBHOOK_SECRET`, `JOBCAST_ADMIN_KEY` (admin
pages — same key for /admin/stats and /admin/support), `JOBCAST_DEMO_USER` / `JOBCAST_DEMO_PASS` (the
restricted-demo basic-auth gate; the public jobbreak.ai is open), `JOBCAST_SUPPORT_EMAIL` (default
support@jobbreak.ai), `JOBCAST_BLS_KEY` (CPI), `JOBCAST_SNAPSHOT`, Resend key for email.

## Where to change what
- Prices → `PRICE_CENTS` in `server/payments.py` (code, then deploy).
- Which payment methods show → Stripe dashboard → Settings → Payment methods (hotmail-linked... see Stripe acct).
- Advice quality / prompts → `server/advice.py`. Scores → `server/engine.py` + the data snapshot.
- The paywall copy / reveal → `server/templates/result.html`. Env/instance → Render (hotmail login).

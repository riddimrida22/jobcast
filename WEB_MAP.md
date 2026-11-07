# JobBreak - Web Product Map

The web is the primary product. Native iOS/Android apps (via a Capacitor wrap of this
same frontend) come later and reuse everything here. This map is the plan of record for
the web build; it supersedes ad-hoc notes. Last updated 2026-11-07.

## 1. Positioning (why anyone uses this over a free web scorer)

The market is crowded on the web and nearly empty in the app stores, and no one has won.
The moat is not the score (many give one). It is:

- **The "when".** A sourced timeline, not just a 0-100 number. Most competitors stop at a score.
- **Local truth.** Metro-level demand and pay (BLS OEWS, 393 metros).
- **Defensible method.** Scores from published research (O*NET, Eloundou, BLS), sources shown.
  Never an LLM-invented number. Many rivals are opaque or LLM-scored.
- **Researched, cited, local advice** (paid). City-specific pathways, programs, pay, with
  sources. This is the thing worth paying for and what a free score cannot match.

Framing rule (non-negotiable, from CLAUDE.md): ranges and timelines, never a flat verdict
that a job is gone. Urgency is about acting in the window, not doom.

## 2. Audiences (the web speaks to whoever enters a job)

| Segment | Hook | Primary channel |
|---|---|---|
| Mid-career 35-55 (core payer) | 15+ years left, rules changing; protect income | FB/IG, YouTube |
| Knowledge workers | LLMs already do part of the job; highest pay-intent | LinkedIn, Reddit, X |
| Trades / blue-collar | Robots + self-driving; physical-robotics score is ours alone | TikTok, trade forums |
| Students + parents | Don't train 4 years for a vanishing job (see /students) | Counselors, parent groups |
| Just-laid-off / switchers | Find the safer adjacent job that pays the same; high intent | Search intent |
| Curious / viral | Shareable score card; top-of-funnel growth, not revenue | Shareable result image |
| B2B: unions / HR / workforce boards | Sourced risk + reskilling path for members | Direct (separate track) |

Creative unlock: the app knows the SOC family the moment a job is picked, so the hero
slogan and visual can switch to match the segment (LLM motif for knowledge work, robot/
self-driving for trades, degree-path for students). One engine, audience-targeted messaging.

## 3. Sitemap

### Live now
- `/` Home: slogan, assessment form, resume auto-fill, at-risk/resilient tickers, score footnote
- `/assess` (POST) -> Result: exposure, timeline, drivers, wages, adjacent roles, paid advice deck, slideshow
- `/jobs` Browse all occupations
- `/jobs/<soc>` Per-occupation page (programmatic SEO, generic read, shareable URL)
- `/students` Future careers (filter by field, education, priority)
- `/methodology` How it works + sources
- `/login` Branded preview gate (username + password, show/hide toggle)
- `/resume` (POST) resume parse; `/subscribe` (POST) email capture
- `/v1/*` JSON API: health, suggest, assess, whatif, plan, advice (feeds web + future apps)

### Planned
- Shareable score card: a per-result OG image + short URL ("My job is 78% exposed - what's yours?")
- Trust band: visible "Sources + last updated" on every result
- FAQ: "Is this just fear-mongering?" reinforcing ranges-not-verdicts
- B2B landing page: unions / HR / workforce boards
- Account + saved results (only once real sign-in / paid tiers go live)
- PWA: installable web app (bridge to the app stores)

## 4. Core user flow

Acquisition (SEO /jobs pages, shared score cards, ads by segment)
  -> Home: audience-matched hero
  -> Assessment form (or resume auto-fill)
  -> Result: score + timeline + drivers + adjacent roles  [free, deterministic]
  -> Share score card  (viral loop back to Acquisition)
  -> Paid advice deck: researched, cited, local plan + slideshow  [conversion]
  -> Email capture -> "outlook changed" notifications  [retention; becomes push on native]

## 5. Monetization (web)

- Free: score, timeline, adjacent roles, deterministic strategies. Drives sharing + SEO.
- Paid tiers (annual pricing live): researched, cited, local advice decks. Haiku/Sonnet/Opus
  by tier. Note the low consumer price anchor set by rivals (~$3/mo, ~$20 lifetime).
- B2B licensing: likely the durable revenue; consumers pay little for a one-time check.

## 6. Build order (priority)

P0 - polish + trust (cheap, high impact)
  1. Accessibility pass: 16px inputs (stop iOS zoom), visible focus, contrast AA, chart text fallback
  2. Fix brand "Break" swing overlapping nav on mobile
  3. Trust band on results (sources + last updated)
  4. Plain-language verdict line atop results (one sentence before the number)

P1 - growth + conversion
  5. Shareable score card (OG image + short URL) - the viral engine
  6. Dynamic audience-targeted hero (slogan + visual by SOC family)
  7. DNA "human edge" motif wherever human/humanness appears (starts with the
     "Lean into the human edge" strategy icon, engine.py:339)
  8. "Is this fear-mongering?" FAQ + progressive (collapsible) form

P2 - platform + reach
  9. PWA installability (manifest, service worker, offline last result)
  10. B2B landing page
  11. Then: Capacitor wrap -> iOS + Android (push notifications as the native hook)

## 7. Open decisions
- Mobile build approach (Capacitor wrap recommended), iOS build via cloud service (Windows
  dev box), Apple ($99/yr) + Google Play ($25) accounts. Deferred until the web map is set.
- Real user accounts: only when paid tiers go live; until then, email capture only.

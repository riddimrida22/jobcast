# Action memo — testing the distributed-compute idea

_Companion to `distributed-compute-note.md`. A sequence of cheap, reversible steps to find
out whether there's a business here before spending real money. Drafted 2026-11-07._

## TL;DR

Don't build a GPU marketplace. **Pick one narrow wedge, sell it before you build it, and
let paying interest — not enthusiasm — decide whether to continue.** Recommended starting
wedge: **privacy-first hybrid inference** (local small model + cloud escalation) for a
single regulated vertical, _or_ a **carbon/cost-aware scheduler** priced on savings. Both
are low-capital and have a nameable buyer.

## Decision to make first (before any steps)

Choose the wedge. Criteria: lowest capital, a buyer you can name and reach, defensibility,
and fit with how you want to spend your time.

| Wedge | Capital | Buyer clarity | Moat | Pick if… |
|---|---|---|---|---|
| Privacy-first edge inference | Low | High (regulated firms) | High | you want defensibility + a values fit |
| Cost/carbon-aware scheduler | Low | Medium | Medium | you want fastest ROI story |
| Spot + checkpointing resale | Medium | Medium | Medium | you enjoy infra plumbing |
| Verification/trust middleware | Med–High | Low (early) | High | you're playing a long infra game |
| Consumer GPU buyback | High | Low | Low early | only after verification is solved |

**Default recommendation:** privacy-first edge inference, one vertical (e.g. small law
firms, or independent medical practices).

## Phase 0 — Frame (this week, ~2 days)

- [ ] Write a one-paragraph problem statement for the chosen wedge: _who_ hurts, _how
      much_, _what they do today_.
- [ ] List 3–5 named prospective buyers you could actually email or DM.
- [ ] Define the single metric that would make this a "yes" (e.g. "5 of 10 interviews say
      they'd pay $X/mo and would pilot").

## Phase 1 — Validate demand (weeks 1–3, no code)

- [ ] 10–15 customer discovery interviews. Ask about current pain and spend, **not** your
      solution. ("How do you handle client data + AI today? What's not allowed?")
- [ ] One-page positioning + a static landing page with a waitlist/"request pilot" form.
- [ ] Drive 100–300 targeted visitors (communities, LinkedIn, cold outreach).
- [ ] **Gate:** hit your Phase-0 metric? If no → stop or re-pick the wedge. If yes → Phase 2.

## Phase 2 — Smallest testable thing (weeks 3–8)

- [ ] Build the thinnest prototype that proves the core claim, not a platform:
      - _Edge inference wedge:_ a demo running a small local model on real client-type data
        with cloud escalation, showing "nothing confidential left the machine."
      - _Scheduler wedge:_ a script that takes a real batch workload and shows the
        cost/carbon delta from shifting it to cheap/green windows.
- [ ] Run it with 1–3 design-partner customers (free or near-free) under a light agreement.
- [ ] Instrument one number that matters (data-never-left guarantee met / $ saved).
- [ ] **Gate:** did a design partner get real value and say they'd pay? If no → iterate or
      stop. If yes → Phase 3.

## Phase 3 — First revenue (weeks 8–16)

- [ ] Convert ≥1 design partner to a paid pilot (even a small monthly figure).
- [ ] Write the pricing page; pick a model (subscription for #3; % of savings for #4).
- [ ] Decide the legal entity question (own LLC vs under an existing venture) — mirror the
      open question in `SPEC.md` for Jobcast; don't pre-commit capital before a paying pilot.
- [ ] **Gate:** ≥1 paying customer + a repeatable pitch? Then consider raising/scaling.

## 30 / 60 / 90 at a glance

- **30 days:** wedge chosen, 10+ interviews done, landing page live, go/no-go metric hit or not.
- **60 days:** thin prototype in front of 1–3 design partners, one value metric instrumented.
- **90 days:** at least one paid pilot, pricing defined, entity decision made.

## Guardrails

- Spend on _learning_, not infrastructure, until a customer has paid.
- Every market claim in the note is **to be verified** — re-check competitor pricing and
  the state of decentralised-training tech before using any figure in a pitch.
- Keep this separate from Jobcast's roadmap unless a paid pilot proves it deserves focus.
- Don't touch the hardest walls (verification, consumer buyback, weight security) as a
  _first_ move — they're where incumbents and well-funded teams are already stuck.

## Open questions to resolve

- Which vertical / buyer segment first?
- Solo side-project, or a funded venture from the start?
- Build-vs-partner: ride existing marketplaces (Vast/RunPod) and sell a layer on top, or
  own the stack?
- What's the one claim a design partner must believe for this to work — and can a weekend
  prototype prove it?

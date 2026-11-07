# Distributed & demand-shaped AI compute — strategy note

_Status: exploratory thinking note. Adjacent to Jobcast, not part of the v1 product.
Drafted 2026-11-07. Treat the market claims as a starting map to verify, not settled fact._

## The question

Do AI data centres really need to be so big — and could a lot of that compute be
pushed out to idle capacity that already exists (users' machines, spare datacentre
hours, off-peak windows) instead of being concentrated in ever-larger campuses?

Short answer: **the giant campuses are driven by _training_ and by where power is
available, not by physics.** A large and growing share of the load — inference, batch,
fault-tolerant training — is distributable in space, shiftable in time, or both. The
walls are not "users don't have capacity." They're network coupling, verification, weight
security, and job state.

## The core economic insight: compute is perishable inventory

An idle GPU-second is gone forever the moment it passes — identical to a seat on a flown
plane or an unbooked hotel room-night. That is exactly the inventory Expedia / Hotwire /
Priceline learned to monetise: sell the perishable unit cheap, on worse terms, _without_
undercutting the full-price tier. Any price above marginal energy cost beats the zero you
get from letting the second evaporate.

This single idea underwrites everything below.

## Four levers that could shrink / flatten the demand curve

1. **Local (on-device) inference.** Small models run on the user's own silicon — Apple
   Intelligence, Copilot+ PCs, Gemini Nano, local Llama/Mistral. Strongest argument:
   **privacy** — trade secrets and regulated data never leave the device. Trims the
   inference load; cannot touch training.
2. **Compute buyback (the net-metering analogy).** Users and operators sell spare GPU
   time into a pool, the way utilities buy back rooftop solar. Elegant property: the
   swarm's **supply self-scales with demand** (more awake users ⇒ more awake devices).
3. **Follow-the-sun routing (space).** A global footprint routes each latency-sensitive
   query to whichever region is awake and has headroom, and pours flexible work into the
   regions that are asleep.
4. **Demand-shaping / peak-shaving (time).** Borrow the grid's playbook — peak shaving,
   valley filling, load shifting, demand response — to move flexible jobs into cheap,
   green, cool overnight/weekend troughs.

## The rule that ties it together: match the workload to the resource

| Workload | Time-shiftable? | Geographically splittable? | Right home |
|---|---|---|---|
| **Interactive inference** (chat, autocomplete) | No — answer now | Yes — route to awake region, or run on edge | Edge / mass compute + routing |
| **Flexible / batch & fault-tolerant training** | Yes | Partly (loose coupling only) | Time-shift into valleys; perishable/spot inventory |
| **Frontier training run** (single coupled job) | No — amortise 24/7 | No — microsecond all-to-all sync | Dedicated full-price cluster |

Route the urgent work in **space**; shift the flexible work in **time**; keep the tightly
coupled work in the **cluster**.

## This market already exists — the idea is partly built

- **Cloud spot markets** — AWS Spot, GCP Preemptible, Azure Spot. Literally the airline
  model: unsold capacity at 60–90% off, revocable when a full-price customer appears.
- **GPU broker marketplaces** — Vast.ai, RunPod, SF Compute, Together, Lambda. The
  "Expedia for GPUs" aggregator layer; Vast already pools heterogeneous/consumer cards.
- **Decentralised training research** — Prime Intellect (INTELLECT-1, trained across
  volunteer nodes on multiple continents), Nous Research, Gensyn, Bittensor, Hugging Face
  **Petals** (distributed inference). Low-communication methods (DiLoCo, DeMo) are the key
  that is starting to loosen the network-coupling wall.
- **Carbon/demand-aware scheduling** — Google and others already move flexible compute to
  the greenest hours and places; datacentres are signing grid demand-response contracts.

So the chain **datacentre spot → broker marketplace → individual contributors** is real;
the last link is the current frontier.

## The hard walls (be honest about these)

1. **Network coupling.** Training is one giant _coupled_ calculation; home links are
   ~1000× too slow for all-to-all gradient sync. Low-comms training helps but doesn't
   erase it.
2. **Verification.** How do you know a paid, untrusted node actually did the work and
   didn't return plausible garbage? Verifiable compute / proof-of-learning is unsolved at
   low cost. (Crypto got away with it only because hashes are cheap to check.)
3. **Weight security.** To train on a stranger's machine you must _ship them the model
   weights_ — the lab's crown jewel, now copyable/poisonable. Secure GPU enclaves are
   immature.
4. **Job state / preemption.** A seat is self-contained; a long job has state. Preempting
   it wastes progress unless it checkpoints and resumes elsewhere — so only
   interruption-tolerant work suits perishable inventory.
5. **Efficiency vs flexibility.** A packed datacentre running flat-out is the most
   FLOP-per-watt-efficient thing you can build. Distributed/peak-shaved compute wins on
   **flexibility, resilience, locality, and grid/water impact** — not raw cost-per-FLOP.
   For a well-capitalised lab, the clean cluster is simply cheaper per _useful_ FLOP.

**Net:** these strategies flatten and green the curve and move the marginal unit; they do
not make the baseline training campuses disappear.

## Where the real opportunity is

Not in out-competing hyperscalers on raw frontier training. The open wedges are:

- **Privacy-first hybrid inference** for regulated verticals (law, health, finance,
  defence) — local small model + cloud escalation, data stays on-prem/on-device.
- **Picks-and-shovels for spot/distributed compute** — checkpointing, fault-tolerance,
  verification, routing middleware. Sell to everyone riding the perishable-inventory wave.
- **Demand-shaping SaaS** — carbon/cost-aware schedulers that bank savings for customers.
- **Vertical/regional brokers** — aggregate perishable inventory for a specific buyer
  segment the generalist marketplaces serve badly.

## Monetisation ideas

Ranked roughly by openness of the wedge (crowded → open) and capital intensity:

1. **Perishable-inventory brokerage (Expedia-for-GPUs).** Aggregate spare capacity, match
   to buyers, take a transaction cut. _Crowded_ (Vast/RunPod). Wedge only if verticalised.
2. **Spot-arbitrage + checkpointing-as-a-service.** Buy preemptible capacity, resell it
   as "reliable" by layering automatic checkpoint/resume. Margin = reliability premium.
3. **Privacy-first edge inference SDK/router.** Licence/subscription to enterprises that
   can't send data to the cloud. Highest defensibility; ties to Jobcast's own trust ethos.
4. **Carbon/cost-aware scheduler (SaaS).** Price as a share of the energy/cost savings you
   create. Clear ROI story, low capital.
5. **Fault-tolerance / verification middleware.** The trust layer for untrusted nodes —
   proof-of-compute, reputation, slashing. Infra play; strong moat if it works.
6. **Consumer/prosumer buyback program.** "Sell your idle GPU." Platform fee on each
   matched hour. Depends on solving verification + weight security; longest horizon.
7. **Grid-interactive / demand-response aggregation.** Package datacentre flexibility and
   sell it to utilities. Capital- and relationship-heavy; real money if you have the ins.

Recommended first wedge: **#3 or #4** — lowest capital, clearest buyer, defensible, and
#3 rhymes with Jobcast's "honest, privacy-respecting" positioning.

## Connection to Jobcast (kept honest)

This is an adjacent idea, not a Jobcast feature. The one real tie: **on-device AI removes
the "we can't ship secrets to a cloud model" barrier that currently _protects_ some
confidential-data jobs** (paralegal review, medical note-taking, internal financial
analysis). As local AI matures, those automation timelines move _forward_. That is a
defensible, sourceable factor worth noting in the factor model (see `FACTORS.md`) — not a
reason to pivot the product.

## Further reading to verify the claims above

- Frey & Osborne (2013); Eloundou et al. (2023) — already in Jobcast's source registry.
- Prime Intellect INTELLECT-1 report; DiLoCo / DeMo papers (low-comms distributed training).
- Hugging Face Petals (distributed inference).
- Cloud spot-instance docs (AWS/GCP/Azure); Vast.ai / RunPod marketplace models.
- Google carbon-aware computing write-ups; datacentre demand-response coverage.

_All market/product claims here are from general knowledge as of early 2026 and should be
re-checked before any are used in a pitch or a decision._

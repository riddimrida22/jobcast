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

- **Cloud spot markets** — AWS Spot, GCP Spot VMs (successor to Preemptible VMs, no 24h
  cap), Azure Spot. Literally the airline model: unsold capacity at **~60–91% off**,
  revocable on short notice (AWS 2-minute warning; Azure/GCP ~30 seconds).
- **GPU broker marketplaces** — Vast.ai, RunPod, SF Compute, Together, Lambda. The
  "Expedia for GPUs" aggregator layer; **Vast is a P2P marketplace (~10% commission) where
  hosts set their own rates and turn idle hardware into revenue**, and RunPod's Community
  Cloud resells evictable spare capacity. Reliability varies by host — the perishable-tier
  tradeoff in practice.
- **Decentralised training research** — Prime Intellect **(INTELLECT-1: a 10B model
  trained Nov 2024 across up to 14 nodes on 3 continents from 30 independent providers,
  via a DiLoCo-FSDP2 hybrid with ~400× less communication)**, Nous Research (DeMo/DisTrO,
  and the Psyche network), Gensyn (decentralised training with cryptographic verification),
  Bittensor (subnet incentive network), Hugging Face **Petals** (BitTorrent-style
  distributed inference, up to Llama-3.1-405B). Low-communication methods — **DiLoCo
  (DeepMind, 2023, ~500× less comms) and DeMo (Nous, 2024, up to ~85× less data/GPU)** —
  are the key starting to loosen the network-coupling wall.
- **Carbon/demand-aware scheduling** — Google's Carbon-Intelligent Computing System
  time-shifts flexible workloads (data analytics, AI training, batch) to greener hours and
  can shift them geographically; Google has also described signing grid demand-response
  contracts (reported ~1 GW with US utilities — figure worth confirming against Google's
  own announcement).

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

## Sources & verification (checked 2026-11-09)

Each market claim above was checked against current sources. Status: **all confirmed**,
with the minor refinements already folded into the text. Most third-party pricing figures
vary by region/demand — treat exact percentages as "up to," not guarantees.

| Claim | Status | Primary / best source |
|---|---|---|
| Spot markets ~60–91% off, revocable (AWS 2-min, Azure/GCP ~30s) | ✅ Confirmed | AWS/GCP/Azure spot docs; [DataCenterDynamics guide](https://www.datacenterdynamics.com/en/opinions/complete-guide-spot-instances-aws-azure-and-gcp/) |
| Vast.ai P2P marketplace (~10% commission), RunPod Community = evictable spare capacity | ✅ Confirmed | [Vast.ai docs](https://vast.ai/docs/overview/introduction); [RunPod vs Vast comparison](https://dev.to/theairabbit/runpod-vs-vastai-a-deep-dive-into-gpu-cloud-platforms-for-aiml-10ga) |
| INTELLECT-1: 10B, ~14 nodes / 3 continents / 30 providers, DiLoCo-FSDP2, ~400× less comms (Nov 2024) | ✅ Confirmed | [Prime Intellect release](https://primeintellect.ai/blog/intellect-1-release); [arXiv 2412.01152](https://arxiv.org/abs/2412.01152) |
| Petals = BitTorrent-style distributed inference, up to Llama-3.1-405B | ✅ Confirmed | [Petals (NeurIPS 2023 paper / project)](https://huggingface.co/papers/2312.08361) |
| DiLoCo ~500× less comms (DeepMind 2023); DeMo up to ~85× less data/GPU (Nous 2024) | ✅ Confirmed | [DiLoCo arXiv 2311.08105](https://arxiv.org/abs/2311.08105); [DeMo arXiv 2411.19870](https://arxiv.org/abs/2411.19870) |
| Gensyn (verified decentralised training); Bittensor (subnet incentive network) | ✅ Confirmed | [Gensyn intro](https://www.machinelearningatscale.com/p/decentralised-compute-machine-learning-1); Bittensor docs |
| Google carbon-aware load-shifting; grid demand-response contracts | ✅ Confirmed (1 GW figure unverified) | [Google Carbon-Intelligent Computing (arXiv 2106.11750)](https://arxiv.org/pdf/2106.11750); [Electricity Maps case study](https://www.electricitymaps.com/resources/case-studies/google-data-centers-shift-their-computations-to-cleaner-times-and-locations) |
| On-device AI: Apple Intelligence, Copilot+ PCs (40+ TOPS), Gemini Nano | ✅ Confirmed | Apple (WWDC 2024), Microsoft Copilot+, Google Gemini Nano official docs |
| Frey & Osborne (2013); Eloundou et al. (2023) | ✅ In Jobcast's source registry | `config/sources.json` |

**Caveats that remain:**
- Exact spot discounts and GPU marketplace prices shift constantly; re-pull before quoting.
- Google's "1 GW demand response" figure appears in secondary coverage — confirm against
  Google's own announcement before using it in a pitch.
- Most pricing came from vendor/comparison blogs, not official pages; verify a specific
  number against the provider's pricing page when it matters.
- One footnote of note: DeMo's paper lists Diederik Kingma, done before he joined Anthropic
  — relevant only as a credibility signal for the method.

_Checked 2026-11-09. The direction and magnitudes hold; specific prices are time-sensitive._

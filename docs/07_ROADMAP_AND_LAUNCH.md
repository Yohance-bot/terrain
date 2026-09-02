# 07 — Roadmap and Launch

**Status:** Stable Draft v1

Derived from the TerraRun Statement of Work v1.0, adjusted where the mechanics decided in `01_CORE_MECHANICS` v2 differ from that document. Deviations are listed explicitly in the last section so the two can be reconciled rather than silently diverging.

---

## The Question Phase 1 Answers

**Do people come back?**

That is the whole purpose of the first release. Not whether the territory system is elegant, not whether the map is beautiful, not whether clubs are balanced. Whether a person who ran on Monday runs again on the following Monday because of something this application did.

Every scoping decision below follows from that. A feature earns its place in Phase 1 only if its absence would change the answer.

---

## Phase 1 Scope

**In scope.** Territory generation for the launch districts. GPS activity recording, foreground and background. Route-to-territory matching. The influence engine — decay, diminishing returns, the two ledgers, ownership. Standings. Map and territory interface. Home Territory. XP, levels, Prestige, streaks. Onboarding and the permission flow. Push notifications. Health and Strava import. Integrity v1. Admin console. Analytics instrumentation. Closed beta and store submission.

**Out of scope.** Clubs and club competition. Momentum. Seasons. Coins and the economy. Missions and quests. Checkpoints. Social feed. Commerce and merchant tooling. Cycling. Web application. Multiple cities.

**Why Momentum is cut.** Momentum exists to keep a consistent solo player competitive against a club. There are no clubs in Phase 1, so it has nothing to balance. It returns alongside them.

**Why clubs are cut.** They are the most complex system in the design and the most expensive to have built on top of a loop that turns out not to retain anyone. `01` makes the schema carry club attribution from the first migration regardless, so deferring the feature does not create a migration later.

---

## Development Order

The critical path is not negotiable. Nothing meaningful can be tested until influence works, and influence cannot work until territories exist and runs can be recorded reliably.

```
Sprint 0 — GPS reality test
    Minimal recorder on real hardware
    ↓
Sprint 1 — Map pipeline
    OSM import → territory generation → H3 indexing → admin review → publish
    ↓
Sprint 2 — Core run loop
    Run → upload → territory matching → influence update → reveal
    ↓
Sprint 3 — Closed beta
    ↓
Only then:
    Clubs · social features · sponsorship · checkpoints · missions · Coins
```

Sprint 0 is a gate, not a sprint in the usual sense. The GPS reality test must pass or its failure must be understood and accepted before S1 begins. See `04_APPLICATION_ARCHITECTURE`.

Sprint 1 and Sprint 2 can overlap at the edges — territory generation and the recorder can proceed in parallel once S0 has produced real traces — but Sprint 2 cannot complete until Sprint 1 has published at least one district.

Sprint 3 is a closed beta, not an open launch. Three hundred to a thousand users recruited through existing run clubs in the launch corridor. See Launch Strategy below.

## Sprint Order

The critical path is not negotiable: **territories exist → runs get recorded → influence works → it feels like a game.** Nothing meaningful can be tested until the third of those completes, and map polish must never pull engineers off the influence engine.

| Sprint | Goal | Exit criteria |
| --- | --- | --- |
| **S0** | Setup | Repository, CI, environments. Authentication working end to end. Stack decisions frozen. |
| **S1** | Territories exist | Pipeline generates one district. Polygons reviewed and published through the admin console. H3 index built. Territories render on the map in the app. |
| **S2** | Runs get recorded | Foreground and background recording. Offline queue. Activity submits and persists. **Battery under 6% per 45 minutes** — an exit criterion, not a later optimisation. |
| **S3** | Influence works | Route matching with boundary hysteresis. Influence formula, decay, diminishing returns, two ledgers, standings. Run summary shows the per-territory split. |
| **S4** | It feels like a game | Territory detail, ownership fills, Home Territory, XP and levels and streaks, post-run reveal polish. |
| **S5** | It's an app | Onboarding, permission flow, notifications, Strava import, integrity v1, hold and appeal. **Play background-location submission starts here, not in S6.** |
| **S6** | It ships | Bug burn-down, device matrix, internal beta with a small cohort. |

Two things are pulled earlier than instinct suggests, both because they are blocking rather than because they are urgent:

**The background-location spike happens before S0.** A 45-minute route recorded on a cheap Xiaomi or Realme with the screen off, surviving an app kill, uploading afterwards. It is a week of work that either de-risks the project or reveals that the product needs rethinking, and discovering it in S2 is far more expensive than discovering it now. Traces recorded during this spike also feed the route-matching decisions in `03`.

**Play Store background-location review starts in S5.** Review takes two to six weeks and first-attempt rejections are common. Starting it in S6 means it becomes the thing that blocks launch.

---

## Launch Strategy

**Districts, not a city.** Indiranagar, Ulsoor, Cubbon Park and its surrounds, Lalbagh, Jayanagar, Koramangala. Contiguous, three landmark destinations, and the highest concentration of Bengaluru's run-club culture. Detail in `03_MAP_AND_TERRITORY_PIPELINE`.

**Closed beta, not open launch.** Three hundred to a thousand users. This is a gameplay requirement rather than a caution: territory competition needs density, and a thousand users scattered across greater Bengaluru is an empty world while three hundred inside one corridor is a genuine rivalry.

**Recruit through existing clubs.** The first cohort should come from two or three running groups that already meet in the launch districts. They arrive as an existing social unit, they already run together, and they generate contested territory on day one rather than in month three. This is also the answer to the cold-start problem that no amount of engineering solves.

Sequence: internal beta with roughly fifty users at the end of S6, then public closed beta two weeks later once the first bug wave has been cleared.

---

## Success Criteria

| Metric | Target |
| --- | --- |
| D1 retention | ≥ 55% |
| D7 retention | ≥ 30% |
| D30 retention | ≥ 20% |
| Median active days per week | ≥ 3 |
| Runs per active user per week | ≥ 3 |
| Territories contested by two or more players | ≥ 30% of published territories |
| Crash-free sessions | ≥ 99.5% |
| Battery complaints | < 2% of beta users |

**The stop rule: D30 below 15% means the loop is not working, and Phase 2 does not start.** Fix the loop or reconsider the model. Building clubs on top of a loop nobody returns to only makes the eventual rewrite larger.

### Instrumentation Requirements

Measure from the first build. The decay system cannot be tuned without this data, and the club-compression decision cannot be made retrospectively.

**Core behavioural questions the instrumentation must answer:**

Do people run more often after installing the app?
Do they return after losing a territory?
Do they care about ownership — do they run specifically to defend or reclaim a place?
How often do territories change hands?

**Required metrics from day one:**

| Category | Metric |
| --- | --- |
| Retention | D1, D7, D30 |
| Engagement | Runs per active user per week, median active days per week |
| Gameplay | Territory interactions per run, ownership changes per week, percentage of territories contested by two or more players |
| Behavioural | Return rate after losing a territory, Home Territory defence frequency, time between runs |
| Trust | Held and reversed run counts, appeal volume, appeal overturn rate |
| Performance | Battery complaints, crash-free session rate, reveal latency p95 |

**Tuning inputs** — required for decay half-life calibration: territory ownership duration, ownership change frequency by territory class, how often a player who loses a territory returns to contest it.

**Club compression inputs** — required from the season clubs first ship: ownership by owner type over time, individual-versus-club ownership transitions, solo contribution share per contested territory.

PostHog or equivalent product analytics from the first build. KPI dashboards against the success criteria table above. Funnel and retention tracking from onboarding through first run, first reveal, and first ownership change.

---

## Compliance Timeline

The most under-estimated part of any schedule of this kind.

- **Google Play background location.** Prominent in-app disclosure, declaration form, demo video. Two to six weeks, rejections common. Begins S5. A foreground-only fallback mode must be genuinely usable, both as insurance and as the honest answer for players who decline.
- **Apple.** A clear justification string for always-location authorisation.
- **India DPDP Act 2023.** Explicit consent for location processing, a stated retention period, and an in-app deletion path — all required before public beta, not before public launch. Retention periods are defined in `05_ANTICHEAT_AND_TRUST`.
- **Health platform terms.** HealthKit and Health Connect both prohibit using health data for advertising. Since a commerce layer is on the roadmap, that boundary must be documented before it becomes relevant.
- **Coins.** Not redeemable for money, and never described in language that could be read as redeemable. This is a Phase 2 concern but the constraint is recorded in `01_CORE_MECHANICS` now, because it is a marketing-copy risk as much as an engineering one.

---

## Beyond Phase 1

Each phase gate requires the previous phase's success metrics to be met before it starts.

| Phase | Scope |
| --- | --- |
| **2 · Community** | Clubs and club competition, Momentum, seasons, streak rewards, social features, full health integrations, missions, Coins and cosmetics |
| **3 · Commerce** | Partner map, checkpoint sponsorship, redemption, merchant tooling, events |
| **4 · Intelligence** | Coaching, recovery, habit analytics, recommendations |
| **5 · Impact** | Collective goals, environmental and community missions, corporate and CSR programmes |

Checkpoints are worth noting as the bridge: they are defined as a reserved concept in `01_CORE_MECHANICS` with no mechanic attached, and Phase 3 is where they acquire one. Designing them earlier risks building a gameplay system to fit a commercial requirement that does not exist yet.

---

## Deviations From The Statement of Work

Recorded so the two documents can be reconciled deliberately.

| Area | SOW v1.0 | Decided position | Reason |
| --- | --- | --- | --- |
| Daily influence caps | In Phase 1 scope | **Removed** | A hard daily cap plus permanent influence makes ownership uncontestable — the incumbent and the challenger gain the same maximum per day, so the gap never closes. Replaced by diminishing returns. See `01_CORE_MECHANICS`. |
| Active influence window | Sum of the last 90 days | **Exponential decay by half-life** | A fixed cutoff creates a cliff: full value on day 89, nothing on day 91. Storage is unaffected — the same daily rollup serves both, weighted by age for Active and unweighted for Legacy. |
| Clubs | Phase 2 | **Phase 2 — agreed** | No change. |
| Momentum | Phase 1, cut under the lean option | **Phase 2** | It exists to balance solo players against clubs. There are no clubs in Phase 1. |
| Coins | Phase 1 | **Phase 2** | Does not affect whether the core loop retains people. |
| Missions and quests | Phase 1 | **Phase 2** | Same reason, plus a risk: missions can mask a loop that is not working rather than reveal it. |
| Home Territory | Phase 1 | **Phase 1 — adopted** | It is the answer to the empty-map problem for a new player and it was missing from the mechanics document entirely. |
| H3 cell index | Resolution 10 lookup table | **Adopted**, with an addition | H3 solves lookup cost but not GPS noise at boundaries. Hysteresis and segment assignment are required alongside it. See `03_MAP_AND_TERRITORY_PIPELINE`. |
| Cycling | Decision pending | **Permanently out of scope** | Design and integrity both. Supporting cycling means accepting speeds indistinguishable from a motorcycle. |
| Raw trace retention | Fixes discarded after 30 days | **Decided** — raw fixes 30 days, derived integrity evidence 12 months, polylines reduced at 90 days | See `05_ANTICHEAT_AND_TRUST` evidence retention policy |
| Territory caps in the schema | `player_cap`, `club_cap` | **Replaced** | Territories carry influence capacity and decay half-life instead. |

---

## Decisions Needed Before S0

1. **Scope option** — full scope over roughly five months, or a lean Phase 1 in around thirteen weeks. The lean option is recommended, because everything it cuts is additive later and none of it changes the schema or the answer to the retention question.
2. **Backend engineer** — hire, contract, or extend the timeline. The bus factor on a single engineer is the largest schedule risk in the plan.
3. **Which district first.** Recommendation: wherever an existing running club already meets.
4. **Where the first three hundred users come from.** This is a recruitment plan, not a marketing one, and it should exist before S0 rather than during S6.
5. **Privacy policy and retention periods**, agreed with `05_ANTICHEAT_AND_TRUST` before store submission.

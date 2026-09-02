# 05 — Anti-Cheat and Trust

**Status:** Stable Draft v1

---

## Purpose

`02_WHAT_WE_REFUSE_TO_BECOME` states, in its own emphasis, that a world which can be manipulated is a world that eventually loses meaning, and that if players stop trusting the map they stop caring about the map. This document is how that commitment becomes engineering.

It defines what must be captured, what states a run passes through before it counts, how influence is recorded so that it can be undone, and how the platform responds when it believes a run is not real.

**What this document is not.** It is not a detection algorithm. Detection rules will change constantly and should not be written into a design document, both because they will be wrong at first and because publishing them is a gift to the people they are meant to stop. What is specified here is the architecture that makes detection possible, improvable, and reversible.

---

## The Honest Position

A phone cannot prove that a person moved. It can only produce evidence that is expensive and inconvenient to fabricate.

This is not solvable in principle, and any document claiming otherwise is lying. The realistic goal is:

- Make cheating **expensive** — it should require sustained effort, not a downloaded app.
- Make cheating **boring** — the game design should ensure the payoff is small.
- Make cheating **reversible** — when it is found, the damage to the shared world can be undone.
- Make honest play **never punished** — a false accusation costs more trust than a missed cheater.

That last point deserves emphasis. Bangalore has dense tree cover and tall buildings, and GPS accuracy of twenty to fifty metres is routine for honest players. Any detector aggressive enough to reliably catch a scooter will also flag real people. The system is therefore designed to be **conservative in enforcement and permanent in evidence**: we keep enough data to revisit any run later, and we act slowly.

---

## Design Support From The Game Itself

The most durable anti-cheat is economic, and `01_CORE_MECHANICS` already provides most of it.

**Diminishing returns** mean that influence gained in a place the cheater already dominates approaches zero. Fabricating a hundred kilometres in Cubbon Park is worth barely more than fabricating ten.

**Decay** means a cheater cannot cheat once and hold a place forever. They must keep cheating indefinitely, which converts a single anomalous event — hard to detect — into a sustained pattern, which is easy to detect.

**No purchasable advantage** means there is no market. There is nothing to sell and no economy to farm for.

**Square-root compression of effort** means that even successful fabrication yields a compressed advantage. Ten times the fake effort is roughly three times the standing.

Design choices that make cheating unrewarding are worth more than any classifier, and should be preferred whenever the two conflict.

---

## Principle 1 — The Client Asserts Nothing

The application uploads observations. The server derives every fact that matters.

The client never submits distance for scoring, never submits which territories it believes were crossed, never submits influence, and never submits a validity judgement. It may compute distance for live display; that number never leaves the device as truth.

This is stated in `04_APPLICATION_ARCHITECTURE` as a responsibility boundary. It is repeated here because it is the load-bearing anti-cheat decision. The moment any derived value is trusted from the client, every historical record becomes suspect and the only remedy is a full reprocessing and a trust reset.

---

## Principle 2 — Capture Evidence From The First Run

**This is the only genuinely irreversible decision in the document.** A run recorded without this evidence can never be validated later, no matter how good detection becomes. Every run recorded before capture exists is permanently unverifiable.

Every location sample carries:

| Field | Why |
| --- | --- |
| Timestamp | Ordering, gap detection, time-of-flight plausibility |
| Latitude and longitude | The trace itself |
| Horizontal accuracy | Distinguishes urban-canyon noise from fabrication; a trace that is *too* accurate is itself a signal |
| Altitude and vertical accuracy | Terrain consistency |
| Speed and bearing, as reported | Reported values disagreeing with computed values is a strong signal |
| Provider | GPS, network or fused — a trace that never uses satellites is suspicious |
| Mock provider flag (Android) | Direct indication of a simulated location |

Every run additionally carries:

| Field | Why |
| --- | --- |
| Step count for the session, from the platform pedometer | The cheapest and strongest signal available: distance without steps is not running |
| Coarse accelerometer activity summary | Motion consistent with walking or running, versus a stationary device or a vehicle |
| Platform activity classification, where available | The operating system's own opinion about whether this was walking, running or in-vehicle |
| Device integrity attestation result | Play Integrity or App Attest verdict at time of submission |
| Application and pipeline version | So a bug can be distinguished from an attack |
| Recording interruptions and permission state | Honest explanation of gaps |

Raw submitted payloads are stored unmodified in object storage, separately from the derived run record, so that any run can be re-examined against future rules.

---

## Principle 3 — A Run Has A Lifecycle, Not A Boolean

```
submitted  →  validated  →  applied
     ↓            ↓            ↓
  rejected    provisional   challenged  →  reversed
```

- **submitted** — received, stored, not yet processed.
- **validated** — passed automated checks.
- **provisional** — accepted but held under suspicion. Counts for the player's personal statistics; does **not** yet contribute influence.
- **applied** — influence granted, standings updated.
- **rejected** — never counted. Reserved for unambiguous cases such as an explicit mock-location flag.
- **challenged** — an applied run later suspected.
- **reversed** — its influence has been withdrawn and standings recomputed.

Territory standings are computed only from **applied** runs.

Retrofitting this state machine under a live leaderboard means downtime and visible score changes for honest players, which is why it exists from the first release even while the rules that drive it are naive.

### Apply Optimistically, Reverse When Necessary

The default flow for every normal run:

```
Run completes
    ↓
Influence applied immediately
    ↓
Reveal shown to player
    ↓
Validation continues in background
    ↓
Reverse only if cheating is confirmed
```

Do not delay normal players. A delayed or broken reveal damages retention more than temporary cheating that is later reversed.

Provisional holds are reserved for a small set of strong, unambiguous signals only:

explicit mock-location provider flag
physically impossible movement — teleportation, sustained vehicle speed
clear device manipulation — failed attestation, emulator signature
identical trace repeated to sub-metre precision across accounts

Everything else is applied immediately and reviewed asynchronously. The append-only ledger makes reversal cheap, correct and recomputable. A broken reveal is not recoverable.

---

## Principle 4 — Influence Must Be Reversible

Influence is recorded as an **append-only ledger**. Every grant references the run that produced it, the territory version it applied to, and the pipeline version that computed it. Standings, ownership and Legacy are all derived and rebuildable from that ledger.

A stored balance that only goes up cannot be corrected. With a ledger, three necessary operations become routine:

- **Reversal.** Voiding a cheater's runs and recomputing standings, so a cheat that held a park for three months does not permanently corrupt its history.
- **Reprocessing.** Rules will change — decay half-lives, effort weights, the diminishing returns exponent. Re-running the pipeline over stored raw data is the only way to change them without discarding history.
- **Migration.** Moving influence across a territory boundary version. See `03_MAP_AND_TERRITORY_PIPELINE`.

This is a hard requirement on the data model, not a preference.

---

## Principle 5 — Every Run Carries A Confidence Score

Validation produces a confidence score rather than a verdict. The score determines whether the run is applied, held provisional, or queued for human review.

The signal families, without their thresholds:

**Physical plausibility.** Speed, acceleration and sustained pace against human limits, evaluated with tolerance for downhill sections and for GPS noise. Vertical movement against terrain.

**Sensor agreement.** GPS distance against pedometer steps is the primary check. Accelerometer energy against claimed activity. Platform activity classification against claimed activity.

**Signal characteristics.** Accuracy that is implausibly good, sampling that is too regular, movement that follows road geometry too exactly, positions that snap rather than drift, traces with no jitter at all. Real GPS is messy; fabricated GPS usually is not.

**Route behaviour.** Movement through buildings, water, or walls. Impossible transitions between samples. Identical traces repeated to sub-metre precision.

**Device and account context.** Attestation failure, mock providers, emulators, rooted or jailbroken devices, several accounts on one installation, and accounts whose behaviour changed abruptly.

**Population context.** A run that is anomalous relative to that player's own history, and relative to what is normal in that territory.

No single signal decides anything. Honest runs fail individual checks constantly.

---

## Principle 6 — Enforcement Is Quiet And Slow

**Suspicious runs are held provisionally and silently.** The player is not told which signal fired. Telling a cheater exactly what tripped the detector is how you train them to evade it.

**Nobody is publicly accused.** There are no cheater labels, no public flags, no shaming. `02_WHAT_WE_REFUSE_TO_BECOME` forbids competition becoming hostility, and a false accusation is unrecoverable.

**Action is graduated.** Provisional holds, then reversal of specific runs, then account restriction, then account termination. Termination is reserved for sustained, unambiguous, deliberate manipulation.

**There is an appeal path.** A human reviews it. Honest players get caught by any system, and the cost of a wrong reversal is far higher than the cost of a missed cheater.

**Reversals are handled gently.** When a cheater's influence is withdrawn and a territory changes hands, the players who benefit are told that standings were corrected. They are not told who was reversed or why.

---

## Trust Tiers By Source

| Source | Influence | XP and streaks | Personal statistics |
| --- | --- | --- | --- |
| Tracked Run, validated | Yes | Yes | Yes |
| Tracked Run, provisional | Held until resolved | Yes | Yes |
| Ambient Activity from platform health data | No | Yes | Yes |
| Imported from a third-party service | No | No | Yes |

**Imported activity never generates influence.** A GPX file is a text document; treating one as evidence of physical presence would make the entire territory system meaningless. Ambient Activity is trusted for XP because it comes from the operating system's own low-power step counter and carries no location, so it cannot be converted into a claim on a place.

This is declared before launch deliberately. Granting influence to imports and withdrawing it later would take territory from players who did nothing wrong, which is far worse than never granting it.

**Cycling and other wheeled activity are permanently out of scope**, as stated in `01_CORE_MECHANICS`. This is partly a design decision and partly an anti-cheat one: supporting cycling would require accepting speeds indistinguishable from a motorcycle, which removes the single clearest physical boundary the system has.

---

## Data Retention And Evidence Policy

Raw GPS traces are among the most sensitive data the system holds. They must not be kept forever simply because they can be. The policy below balances integrity against privacy and against India's DPDP Act 2023 obligations.

### What Is Stored, And For How Long

**Raw GPS sample-level traces — short retention.**

Full-fidelity per-fix location data is retained for **thirty days**, then destroyed. This is the minute-by-minute record of where a person was. Keeping it longer creates unnecessary location history and increases regulatory exposure without proportional benefit once validation has run.

**Derived integrity evidence — long retention.**

Compact per-run evidence is retained for **twelve months**. This is not a movement history — it is a few hundred bytes per run and carries most of the retrospective detection value:

speed profile
accuracy distribution
step count versus GPS distance
altitude changes
provider mix
device integrity attestation result
confidence score and which signals contributed
pipeline version

A cheat that is undetectable in month one and obvious in month six can still be proven from this evidence even after the raw trace is gone.

**Derived gameplay records — permanent.**

Distance, duration, territories crossed, influence granted, ownership changes. These support Legacy and competitive history. They are anonymised, not deleted, on account deletion, because removing them would silently rewrite other players' standings.

**Route polylines — reduced precision after ninety days.**

The submitted route line is stored at full precision for ninety days, then reduced to a simplified polyline sufficient for display in the player's own history but not for re-validation.

### Rules

Raw traces are encrypted at rest. Access is limited to automated validation and to the named review process in `06_ADMIN_AND_OPERATIONS`. They are never used for advertising, never sold, and never shared.

Deletion requests remove raw traces immediately regardless of the retention window. Derived integrity evidence is anonymised. Gameplay records are anonymised rather than deleted.

The privacy policy states all of this in plain language before the first store submission. The retention periods must be agreed before S0 and must match what is declared to the app stores.

---

## Requirements This Places On Other Systems

Stated explicitly so they are not lost:

1. The run record carries `status`, `confidence_score`, `pipeline_version` and `raw_payload_uri` from the first schema migration.
2. Influence is an append-only ledger with reversal, never a mutable balance.
3. Standings and ownership are derived and fully rebuildable from the ledger.
4. Territory standings read only applied runs.
5. Every influence grant references a territory version.
6. The client submits raw observation only.
7. Sensor evidence is captured by the application from its first release.
8. Device attestation runs at account registration and at run submission.
9. There is an internal review queue with reversal and appeal, before the first city launches.

---

## Open Questions

1. **Detection thresholds.** Every one of them. These require real data from real players and cannot be set in advance.
2. **Attestation strictness.** Rooted and jailbroken devices are a meaningful signal, but excluding them outright also excludes legitimate technical users. Where the line sits is undecided.
4. **Whether provisional runs are visible to the player at all**, and in what words.
5. **How a reversal is communicated** to players whose standing changes as a result.
6. **Multi-account policy.** Whether several accounts on one device are blocked, throttled, or merely flagged.
7. **Group runs.** Several players running together legitimately produce near-identical traces, which is also what coordinated fabrication looks like. Distinguishing them is unsolved.

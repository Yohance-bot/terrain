# 06 — Admin and Operations

**Status:** Stable Draft v1

---

## Purpose

This document defines the internal tooling required to run the game, and the operational procedures that tooling exists to support.

It is not a supporting document. Several commitments made elsewhere — human review before a city is published, an appeal path for a reversed run, tuning constants set from real play — are not features of the player-facing application at all. They are promises that can only be kept by an internal console, and without one they are not promises, they are intentions.

---

## Why This Exists

The moment real people are playing, all of the following become routine rather than hypothetical:

- A run is flagged as spoofed and the player says it was not.
- A territory boundary is wrong, cuts a park in half, or has a name locals do not use.
- A player loses influence because of a bug and wants it back.
- A decay half-life is too slow and landmarks have stopped changing hands.
- Someone reports another player for harassment.
- A run needs reprocessing after a rule change.

**None of these may be handled by editing the production database.** Direct database editing has no audit trail, no validation, no reversibility and no accountability, and in a system whose entire premise is a trustworthy shared world, an untraceable manual write is a integrity failure of the same kind as a spoofed run.

Every operational action is performed through the console, is validated, and is logged.

---

## Console Surfaces

### Territories

The tool that makes "AI proposes, humans publish" real. Without it there is no publishing pipeline, and no city can launch.

**Territory editor requirements:**

- view territory polygons on a map with ownership and gameplay metadata overlaid
- edit boundaries — drag vertices, add and remove points
- rename territories
- merge two adjacent territories into one
- split one territory into two, with influence migration preview
- adjust importance, influence capacity, decay half-life, strategic value, playable flag
- run safety and exclusion passes before publish
- preview gameplay impact — how many players are affected, what standings would change
- publish a new version, which freezes the geometry and triggers H3 index rebuild
- version history and diff against the previously published version

**Important rule:** no direct production database edits. Every gameplay-impacting change must:

- create an audit record
- record who made the change and why
- increment the territory version
- be reversible through the versioning system

The exclusion and safety passes are enforced here before publish, not as a separate manual step. `02_WHAT_WE_REFUSE_TO_BECOME` forbids the game encouraging players into unsafe or private places, and the only mechanism that enforces that is a human looking at a map before it ships.

### Players

- Lookup by identifier, display name or phone
- Profile, Home Territory, level, standing summary
- Activity history with status and confidence score
- Trust history and any holds or reversals
- Support actions: restore influence lost to a defect, correct a display name, reset Home Territory
- Restrict or terminate an account, with a required written reason

### Activities and Moderation

- Inspect a single run: map trace, speed profile, accuracy distribution, sensor evidence, attestation result, confidence score and which signals contributed to it
- Approve a held run, or reverse an applied one
- Appeal queue, with the player's statement and the evidence side by side
- Bulk reversal for a confirmed cheating account, with recomputation of every affected territory

Reversal must show the operator what it will change before it is applied — which territories change hands, whose standing moves — because a reversal has consequences for players who did nothing wrong.

### Reports and Safety

- Harassment and abuse reports queue
- Block and report history
- Ability to remove a player from public standings without terminating them

This surface is small and it is not optional. The Vision commits to competition never becoming harassment, and a commitment with no queue behind it is decoration.

### Game Tuning

Every constant in `01_CORE_MECHANICS` lives in a configuration table, edited here, versioned and audited. **No gameplay constant is ever hardcoded in application source.**

- Decay half-lives by territory class
- Diminishing returns exponent
- Effort weights and the walking multiplier
- Minimum presence thresholds
- Home territory bonus
- Territory inactivity floor
- XP and Prestige rates

The entire premise of the tuning-constant table in `01` is that these numbers are wrong until real play corrects them. If changing one requires a release, they will not be corrected often enough, and the game will ship with whatever was guessed first.

Changes are versioned, take effect at a stated time, and are recorded. A change that alters existing standings must state so explicitly before it is applied.

### Operations

- Reprocess a set of runs against a new pipeline version
- Republish a city and migrate influence across territory versions
- Feature flags and phased rollout
- Job queue health, failure and retry visibility

---

## Audit and Access

**Every administrative action is written to an immutable audit log** — actor, action, target, before and after values, reason, timestamp. The log is append-only and is not editable through the console.

**Access is role-based and least-privilege.** Territory review, player support, moderation and tuning are separate roles. Very few people need all of them.

**Viewing a player's raw location trace is a privileged action** and is logged as one, with a reason recorded. This is the sharpest privacy surface in the entire system: an operator inspecting a run is looking at exactly where a specific person was, minute by minute. `02_WHAT_WE_REFUSE_TO_BECOME` commits to transparency about what is stored and why, and an internal tool that can silently browse movement history violates that regardless of intent.

Privileged location access requires:

a specific permission level — not available to all admin roles
logged access with actor, target, timestamp and stated reason
periodic review of who accessed what and why
no casual browsing — access is tied to a specific moderation or appeal case

Nobody should casually browse player movement history. The audit log is the accountability mechanism.

Support actions that touch another player's competitive position require a written reason. Nothing is anonymous.

---

## What Ships When

The full console described above is not a Phase 1 deliverable. The minimum required before the first closed beta:

| Surface | Phase 1 minimum |
| --- | --- |
| Territories | Full. Review, edit, topology validation and publish are on the critical path — no city launches without them. |
| Game tuning | Full. Constants must be changeable without a release, or the beta teaches nothing. |
| Activities | Read-only inspection, plus manual reversal. The appeal queue can be a shared inbox at beta scale. |
| Players | Lookup and read. Support actions can be scripted with audit logging. |
| Reports | A queue. It can be simple; it cannot be absent. |
| Operations | Scripted, with logging. A user interface can wait. |

The rule for deciding what is scriptable and what needs an interface: **anything that changes a player's standing needs validation, a reason and an audit entry.** Whether it has a form around it is a convenience question.

---

## Open Questions

1. **Who operates it.** Roles, and who is on call during the beta.
2. **Appeal turnaround target.** A player whose run was reversed is owed an answer within a stated time.
3. **Whether tuning changes are retroactive.** Changing a decay half-life alters existing standings the moment it applies. Whether that is announced, staged, or applied only to new contribution is undecided and has real player-trust consequences.
4. **Data access review cadence** for privileged trace viewing.

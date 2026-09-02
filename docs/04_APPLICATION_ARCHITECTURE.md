# 04 — Application Architecture

**Status:** Stable Draft v1

---

## Purpose

This document defines the mobile application: how movement is recorded, what the player sees and when, what happens when the network or the operating system fails, and which responsibilities belong to the device rather than the server.

`01_CORE_MECHANICS` defines what a run means. This document defines how a run is captured. `05_ANTICHEAT_AND_TRUST` defines what must be captured for a run to be trusted — that document constrains this one, and where they disagree, it wins.

Implementation stack — React Native with Expo Router and TypeScript — is a given. This document specifies behaviour, not libraries, except where a platform capability forces the choice.

---

## The Central Constraint

Everything in this document follows from one fact: **a phone is a hostile environment for continuous location recording, and the phones our players own are the most hostile ones.**

Android in India is dominated by Xiaomi, Realme, Oppo and Vivo. All four ship aggressive proprietary battery managers that terminate background work regardless of what the platform contract says. A run that silently fails to record is not a bug the player forgives — it is the moment they stop trusting the product, and it is the most likely cause of early churn.

Two mature products solve this in different ways, and we borrow from both.

**Strava does not run in the background in the unrestricted sense.** Recording is an explicit, user-initiated session backed by a foreground service with a persistent notification. The operating system treats that as user-visible work and is far less willing to kill it. Points are written to local storage continuously, so a kill costs seconds rather than the run. For the OEM battery managers, Strava's actual answer is to tell the user to change their settings.

**Pokémon GO's background distance tracking does not use GPS at all.** Adventure Sync reads step and distance data from Health Connect on Android and HealthKit on iOS. That data is gathered by the operating system using the low-power hardware step counter, so no application is running and there is nothing for a battery manager to kill. The trade-off is that it yields distance without location.

Neither product solves the OEM problem. They route around it. So do we.

---

## The Two Recording Modes

This is the most important architectural decision in the application.

### Tracked Runs — the only source of influence

An explicit session. The player presses start. The application runs a foreground service with a persistent notification and records GPS continuously until the player presses stop.

Only a Tracked Run can generate territory influence, because only a Tracked Run produces a location trace that can be matched against territories and validated as real movement.

Everything visible in `01_CORE_MECHANICS` — influence, ownership, momentum, territory Legacy — comes from here.

### Ambient Activity — movement that counts, but not for territory

Steps and distance read from Health Connect and HealthKit, collected by the operating system whether or not the application is open.

Ambient Activity contributes to XP, streaks, lifetime distance and personal statistics. It never generates influence and never affects ownership.

This is how the Vision's commitment that walking matters is honoured — the walk to class, the walk with a child to school, the evening walk — without requiring an always-on GPS daemon that would drain the battery, alarm the platform reviewers, and be silently killed on half our target devices anyway.

It is also the correct answer for trust. Ambient data has no location attached, so it cannot be converted into a claim on a place the player did not visit.

### Imported Activity — recorded elsewhere

A run recorded by another application and imported, via Strava OAuth and webhook or via a health platform's activity records. Contributes to personal statistics only. Never influence, never XP that feeds competitive standing.

The reasoning is in `05_ANTICHEAT_AND_TRUST`. It is far easier to declare this now than to take influence away from players later.

The feature is still worth building: a player's history is part of their identity, and importing it makes the application feel like it knows them from the first session. It simply cannot be a source of territorial claim.

Imports must be deduplicated against runs the application recorded itself. A player with Strava sync enabled who records a Tracked Run here will receive the same activity back through the webhook, and it must not appear twice in their statistics.

| Mode | Influence | XP and streaks | Personal stats | Requires app open |
| --- | --- | --- | --- | --- |
| Tracked Run | Yes | Yes | Yes | Yes, to start and stop |
| Ambient Activity | No | Yes | Yes | No |
| Imported Activity | No | No | Yes | No |

---

## Recording A Run

### While recording

- A foreground service with a persistent, non-dismissable notification on Android, declared with the location service type.
- A wake lock held only as long as the session.
- Location updates at approximately 1 Hz with the highest accuracy the device offers, configured for fitness activity.
- Every sample appended to on-device storage immediately. Never held only in memory. If the process dies, the loss must be measured in seconds.
- Sensor data captured alongside location for validation — see `05_ANTICHEAT_AND_TRUST` for the required fields. This is not optional and cannot be added later.
- Auto-pause when the player stops moving, with manual pause available.

### Failure and recovery

- On launch, the application checks for an interrupted session and offers to recover it. The player should never lose a run to a crash without being told.
- If the process was killed mid-run, everything written up to that point is preserved and submitted.
- Runs shorter than a minimum distance are discarded rather than submitted.
- The recording state must be obvious at a glance. If tracking has stopped, the player finds out immediately, not two hours later.

### On the OEM problem

During onboarding, and again after any detected recording interruption, the application detects the device manufacturer and deep-links the player directly into the specific battery optimisation and autostart settings screen for that OEM, with plain instructions. This is the industry-standard mitigation and the only one that works.

Where the platform cannot guarantee background execution, the application degrades honestly: it tells the player what happened rather than silently producing a broken track.

### iOS

Always authorisation, background location updates with the fitness activity type, and automatic pausing disabled so the system does not stop updates on our behalf. Significant-change monitoring is used to relaunch the application if it is terminated mid-session. A Live Activity showing the run in progress keeps the session visible to the system and to the player.

Note that iOS allows a player to grant only reduced-accuracy location. Detect this and explain, rather than recording an unusable track.

---

## Permissions

Permissions are the first place a player can silently make the product not work.

The sequence:

1. Explain before asking. A screen that says what location is used for and why the game cannot work without it, in the player's terms, before any system dialog appears.
2. Request while-using-the-app permission first, at the moment the player starts their first run — not on launch.
3. Request always-on permission only later, and only when the player has already recorded successfully at least once and the reason is concrete.
4. Request activity and fitness recognition permission when Ambient Activity is first offered, framed as "count your walks too."
5. Request notification permission only after the player owns something worth being told about.

If a permission is denied, the application continues in a reduced mode and says clearly what is not working. It never nags and never blocks the interface behind a permission wall.

Play Store approval for background location requires a separate declaration and a video demonstration, and is frequently rejected on the first attempt. Budget several weeks. Keep a foreground-only mode that is genuinely usable, both as a fallback and as the honest answer for players who decline.

---

## Offline Behaviour

Recording is entirely local and must work with no connectivity, in a basement, in aeroplane mode, for the full duration of a run. Connectivity is required only to submit.

- Completed runs enter a local upload queue and are retried with backoff until accepted.
- Every run carries a client-generated identifier, assigned when the session starts. Submission is idempotent — retrying after a failure that actually succeeded must never produce a second run.
- The queue survives app restarts and device reboots.
- Cached territory shapes and the last known territory state remain viewable offline. The map is degraded but not blank.
- The player can see queued runs and their submission state. Nothing pending is ever invisible.

### Offline Map Strategy

The launch region must support offline map availability.

Running environments frequently have weak connectivity — parks with poor signal, underground sections, dense urban interference, and the tree cover that is common across the launch districts. A player who cannot see the map while recording loses trust in the product even if the run itself is captured correctly.

The initial release bundles cached map data for the launch districts:

Cubbon Park and surrounds
Lalbagh
Indiranagar
Koramangala
Jayanagar
Ulsoor

Without network access the application must still:

display territory polygons and ownership fills from cache
draw the live route as it is recorded
record and persist the activity locally
queue the run for upload when connectivity returns

Territory shapes and the last known ownership state are cached on first load and refreshed when a published version changes. Map tiles for the launch districts are bundled or pre-downloaded on first open. The cache has a bounded on-disk size with a stated eviction policy — oldest district tiles are dropped first when the budget is exceeded.

Offline does not mean offline influence calculation. Territory matching and influence computation happen on the server after upload. The offline guarantee is that recording never fails and the map never goes blank.

---

## What The Player Sees, And When

### During a run — running metrics only

The application behaves as a competent running app. Distance, elapsed time, current and average pace, the route drawn as it happens, and splits.

These exist because they are the reason a player trusts the application enough to record with it at all. A player will not switch from a tool that works to one that does not, however good the game is.

**No territory information is shown during a run.** No entering-territory alerts, no live ownership, no influence counter, no notification that someone is contesting a place. This is a hard rule and it comes from two places: the Vision's principle that the application should disappear while the player moves, and the refusal document's prohibition on encouraging players to chase notifications while moving. A player looking at their phone to check whether they have taken a park is a player not looking at traffic.

### After a run — the reveal

The centrepiece of the product. The feeling being engineered is *"I wonder what changed."*

The reveal shows, in this order of emphasis:

1. What changed in the world — territories taken, lost, defended, or approached.
2. Who the player is now competing against, and how close it is.
3. What their club gained or defended.
4. What this run added permanently to their record in those places.
5. The ordinary run summary — distance, time, pace, route, splits.

Framing rule, carried from `01_CORE_MECHANICS`: because influence shares are relative, a player's percentage falls when other people run. This is always presented as *others gained*, never as *you lost*. The distinction is small in wording and large in how the game feels.

If a run is still being validated, the reveal says so plainly and updates when processing completes. It never shows a provisional result as final.

Under the optimistic validation posture in `05_ANTICHEAT_AND_TRUST`, the reveal shows results immediately for all runs except those held on strong unambiguous signals. A delayed or empty reveal is worse for retention than a result that is later corrected.

### The map

The map is the home surface. It shows territories filled by ownership, the player's own holdings distinguished, contested places legible at a glance, and their own position.

Static territory shapes are fetched once per city region, cached aggressively, and refreshed only when the published version changes. Live ownership state is fetched separately and joined to the shapes on the device. Shapes render immediately from cache while state loads behind them. See `03_MAP_AND_TERRITORY_PIPELINE`.

Ownership colouring is applied through the renderer's feature state rather than by rebuilding the geometry source on every refresh, so that a state update does not cost a full re-parse of the city.

### Map Tile Strategy

Development uses OpenFreeMap. Production migrates to self-hosted PMTiles on Cloudflare R2 and a CDN. The renderer never changes — only the tile source URL.

See `03_MAP_AND_TERRITORY_PIPELINE` for the full migration rationale and trigger conditions. The application must treat the tile source as configurable from the first build so the switch requires no renderer changes.

---

## GPS Recording Reality Test

Before major development begins — before S0, not during S2 — build a minimal recorder and run it on real hardware.

This is the highest-risk unknown in the entire project and it is cheap to test. A week of work that either de-risks everything downstream or reveals that the product needs rethinking before months are spent on top of a broken foundation.

Devices to test:

Xiaomi
Realme
Oppo
Vivo
Samsung
OnePlus

Conditions to test:

screen off for the full duration
application backgrounded
battery saver enabled
45-minute continuous run
application force-killed mid-run, then recovered
poor or no network during and after the run

Success criteria:

a complete route survives all of the above
the route uploads correctly once connectivity returns
battery consumption is under 6% for a 45-minute run
force-quit loses no more than 30 seconds of track

Traces recorded during this test also feed the route-matching algorithm decisions in `03_MAP_AND_TERRITORY_PIPELINE`. They are the ground truth for hysteresis and segment-assignment tuning.

This test is Sprint 0. Nothing else starts until it passes or its failure is understood and accepted.

## Notifications

Notifications are the retention mechanism and the single easiest way to violate the project's own principles. The rules:

- **Never during a recorded activity.** No exceptions.
- **Retrospective, not live.** A player learns that they lost a territory in a daily digest, not the moment it happens.
- **Batched.** Multiple events become one message.
- **Quiet hours on by default.**
- **No manufactured urgency.** Nothing that says a streak is about to break, nothing counting down, nothing implying the player has failed by resting. The refusal document forbids it and it is also simply bad for the people we are trying to help.

Worth sending: someone took a place you held. Your club defended something. A season result. A place you care about became contested.

Not worth sending: nothing happened today. You have not run in three days. Somebody is close to overtaking you, right now, hurry.

---

## Client And Server Responsibilities

The division is not negotiable, because it is also the anti-cheat boundary.

**The application is responsible for** recording location and sensor samples, persisting them locally, queueing and submitting them, rendering the map and territory state, showing running metrics, and presenting whatever the server says happened.

**The application is never responsible for** computing distance for scoring, deciding which territories a route crossed, calculating influence, resolving ownership, or determining whether a run is valid. It may compute a distance figure for live display during a run; that number is for the player's eyes and is never submitted as truth.

The client asserts nothing about the game. It reports raw observation and renders results.

---

## Platform And Accounts

**Both platforms from the start.** iOS and Android are supported from the first release. Retrofitting a platform later forces architectural compromises, and background location behaves differently enough between the two that discovering iOS's constraints late would be expensive.

**Sign-in:** Google, Apple, and phone OTP. Apple sign-in is required by App Store policy once any third-party sign-in exists; phone OTP is the Indian norm and should not be an afterthought.

Anonymous play may be considered later but is not in the first release. Identity matters here because ownership and history are persistent and public, and because account identity is an anti-cheat anchor.

Each installation is bound to the account at registration for integrity purposes. See `05_ANTICHEAT_AND_TRUST`.

---

## Privacy Defaults

These are defaults, not preferences to be discovered in a settings screen.

- Profiles are public. Achievements, territory ownership and aggregate statistics are visible.
- **Routes are private.** Other players never see a route line, a start point, an end point, or the time of day a person runs. Territory ownership already advertises where someone runs regularly; adding timing and exact routes would make the product a stalking tool. This is a safety requirement.
- Start and end points are fuzzed in anything shown to another player.
- A player may withdraw from public standings entirely and still play.
- Accounts belonging to minors are fully private by default.
- Blocking hides you from the blocked player everywhere, including standings.

---

## Acceptance Criteria

These are hard requirements, verified before release, not aspirations to optimise toward later.

| Requirement | Criterion |
| --- | --- |
| **Battery** | A 45-minute recorded run consumes **under 6%** battery on a mid-range Android device. |
| **Reveal latency** | Territory results are visible **within 3 seconds** of finishing a run. |
| **Crash resilience** | Force-quitting the app mid-run loses **no more than 30 seconds** of track. |
| **Offline** | A run recorded entirely in aeroplane mode submits successfully once connectivity returns. |
| **Map load** | The map is usable in under 2 seconds on 4G. |
| **Device floor** | Recording works on a 2 GB RAM Android device. |
| **Stability** | Crash-free sessions at or above 99.5%. |

Two of these deserve explanation because they drive architecture rather than polish.

**Battery is the single most common reason fitness applications get uninstalled.** It is a sprint exit criterion, not a later optimisation. A player who notices this app drains more than the one they already use will go back to the one they already use, and no amount of game design recovers that. Sampling rate, accuracy mode, sensor use and screen behaviour are all budgeted against this number.

**Three seconds is what makes the reveal work.** The reveal is the emotional centrepiece of the product, and a player who finishes a run and then watches a spinner for forty seconds has already lost the feeling the run was supposed to produce. This requires that standings update synchronously in cache while the durable write happens behind it, and it requires the optimistic validation posture in `05_ANTICHEAT_AND_TRUST` — runs are applied immediately and reversed later if necessary, rather than held while they are checked.

Also required from the first build: crash reporting and product analytics. Success is defined as behaviour change, and behaviour change is not observable without instrumentation. Territory shape caches must have a bounded on-disk size with a stated eviction policy.

---

## Open Questions

1. **Default recording mode for club members.** Whether a Tracked Run defaults to contributing to the club or to the player, and how visible the Personal Record toggle is. Carried from `01_CORE_MECHANICS`.
2. **Ambient Activity conversion.** Exactly what steps and ambient distance are worth in XP relative to a Tracked Run.
3. **Minimum run length** below which a run is discarded.
4. **Whether the map is browsable outside the player's own city** before more than one city is published.
5. **Onboarding for a player whose neighbourhood is not in the launch corridor** — what they are shown, and whether they can play at all.
6. **Over-the-air update policy** — how aggressively client rules may change under a player mid-season.

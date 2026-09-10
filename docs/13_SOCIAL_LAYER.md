# Social Layer — Friends, Sharing, Challenges, Races and Ghosts

**Status:** Implemented (migrations `0013`–`0017`)

Everything social is gated on one relationship and measured from one ledger.
This document records the decisions that are not obvious from the code.

---

## The account/device seam

Gameplay ledgers stay device-keyed (`01_CORE_MECHANICS`). Friends, challenges
and races are account-level. `services/social.account_device_ids` is the single
seam between the two: anything that measures a player's movement resolves an
account to all of its devices first, so a challenge counts a run recorded on any
linked device — including a developer runner slot.

## Handles

`accounts.handle` is unique, lowercase, and assigned by a **database trigger**
rather than by application code. Accounts are created in three places (provider
auth, developer login, local accounts) and none of them should have to know
about social features; the trigger also covers accounts created before `0013`
and any future creation path. Players can change their handle afterwards.

Search matches an exact account ID, a handle prefix, or a display-name prefix.
Prefix-only is deliberate: substring search over display names turns the account
list into a directory to browse, which is the shape of a stalking tool rather
than a way to add someone you already know.

## Two toggles, per friend, per direction

`friend_share_settings` holds `share_location` and `notify_on_run_start`
separately. Neither is implied by friendship and neither implies the other —
knowing someone went out is a much smaller disclosure than knowing where they
are. Both default to off.

Three further protections:

- A position older than `POSITION_FRESHNESS` (2 minutes) is never returned, so
  closing the app is itself a way to stop being seen.
- `live_positions` holds one row per account, overwritten in place. Presence
  keeps no trail; route history belongs to `runs`.
- `DELETE /v1/social/position` removes you from friends' maps immediately.

`location_expires_at` is what lets a race grant sharing for its own duration
without touching a standing choice. A permanent grant (`NULL` expiry) is never
modified by a race starting or ending.

## Challenges

Metrics are exactly what the pipeline already writes: distance, run count,
moving time, captured area, territories taken. **Step count is deliberately
absent** — nothing in the app counts steps, and a challenge must never be
settled on a number the server cannot verify.

- The window starts when the challenge is **accepted**, not when it is sent, so
  a slow reply never eats into the promised time.
- Unanswered challenges lapse after `DEFAULT_ACCEPT_WINDOW` (36 hours).
- Runs are counted by when they *finished*, giving "fastest to 10 km" an
  unambiguous instant to compare.
- Both players at zero resolves to `nobody`, not `draw`. No stake moves on
  either, but the distinction is worth keeping in the record.
- The challenger can withdraw only while the challenge is still pending. Once
  someone has accepted and started running against it, pulling it out from under
  them is exactly the kind of thing `02_WHAT_WE_REFUSE_TO_BECOME` warns about.

Resolution is idempotent and runs from three places: the challenge list read
path, `POST /v1/social/challenges/tick` (admin token, for an external cron), and
a manual settle. There is no worker process in the deployment to own it.

## Stakes: loop closures only

**Fixed territory cannot be staked.** `territory_ownership` is a derived
projection that `services/ownership.recompute_ownership` rebuilds from the
influence ledger, so a wagered transfer written there would be silently reverted
by the next applied run in that territory. A `captured_area` has real stored
ownership, which is what makes it transferable.

This also keeps faith with the vision: territory is earned by running and only
by running. A loop closure changing hands on a bet is a bounded, reversible-by-
running outcome; a city block changing hands on a bet is not.

A transferred area keeps its `run_id`, so the effort that created it stays
attributed; `transferred_from_device_id`, `transferred_at` and
`transferred_by_challenge_id` record the move. The stake follows the **outcome**,
not the side that put it up — if the challenger wins, what they staked stays
theirs.

An optional entry condition (`require_opponent_area_m2`) is checked at accept
time against the opponent's unioned captured area, so running the same loop
twice cannot satisfy it.

## Races

A pin, a friend, and a proximity radius of 25 m (10–100 m allowed). Arrival is
detected from the position the client is already reporting, so winning never
requires looking at or touching the phone.

Anything that ends a race — arrival, withdrawal, expiry — revokes the temporary
sharing on both sides. An abandoned race lapses quietly after two hours: nobody
is ever told they lost by walking away.

**This is the feature closest to the safety line in `02`.** It is built with
audio-friendly, glance-free feedback, a forgiving radius, no turn-by-turn
routing, no countdown pressure, and either side free to stop at any moment. If
it ever reads as encouraging people to sprint across roads, it should change.

## Ghosts

A ghost stores its **own copy** of the route (`[lon, lat, ms_from_start]`) built
from the server's geometry and sample timestamps. The retention service erases
raw traces from `runs` after the policy window (`0006_privacy_retention`), and a
benchmark that vanishes when a trace is culled would be worse than not offering
one.

- Playback is entirely client-side: the route is fetched once and replayed from
  a local clock, so the comparison keeps working with no signal and the phone in
  a pocket.
- `is_public` publishes the recorded route. `share_live_location` is a separate
  switch on top of it, never implied by broadcasting, and cleared automatically
  if the broadcast is withdrawn.
- Anyone but the owner sees the route trimmed by `PUBLIC_TRIM_M` (150 m) at both
  ends — a broadcast route otherwise advertises where its runner lives. A route
  too short to survive that trim cannot be published at all.
- A broadcast ghost is a permanent, reusable benchmark. Racing it does not
  consume it, and any number of people can attempt it any number of times.
- Broadcast ghosts are **not drawn on the map by default**. They live behind a
  layer the player switches on, because the map's job is the world and your own
  run.

## Delivery

There is no push transport. `social_events` is an in-app feed that every social
feature writes to, and the client polls it. Push notifications would add a
transport on top of this table rather than replace it.

Presence polls at 5 s and only while there is a reason to: recording, racing, or
sharing with at least one friend. Posting a position returns the visible friends
in the same round trip, so a moving player never pays for two requests.

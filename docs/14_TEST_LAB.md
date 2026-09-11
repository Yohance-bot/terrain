# The Test Lab — Exercising Every Feature From The Console

**Status:** Implemented (migration `0018`)

The console can create disposable players and act as them, so every feature —
including the whole social layer — can be driven end to end without a phone.

---

## Why it needs real sessions

Player endpoints are authenticated: `device_id_header` wants a Bearer app
session whose principal owns the device. With `AUTHENTICATED_ACCOUNTS_ENABLED`
on, the pin-based developer login is closed, so before this the console could
write runs through an operator endpoint and nothing else. Friends, sharing,
challenges, races and ghosts were unreachable.

`POST /v1/admin/sandbox/runners` therefore mints a **genuine app session** for a
disposable account, and the console calls the same endpoints the phone calls
with the same two headers. Two consequences worth stating plainly:

- A pass in the lab means the call sequence works on the device. Nothing is
  mocked at the API boundary.
- Any future player endpoint is drivable from the lab the day it exists, with no
  extra plumbing.

## Why that is safe

`sandbox_accounts` is an allowlist, and `services/sandbox.require_sandbox`
refuses anything absent from it. Only `create_runner` ever writes that table. So
the endpoint cannot be pointed at a real player, which is the entire safety
argument — a test asserts it directly.

The lab also requires `developer_mode_enabled` alongside the admin token.

## Why test runners are invisible

Captured areas and standings are public. Ten test runners loose in Jayanagar
would appear on every real player's map and take real ground. So sandbox devices
are excluded from `/v1/captured-areas`, from the standings a territory reports,
and from the leader distance the map colours itself with.

Teardown is the other half: `DELETE /v1/admin/sandbox/runners` removes the
runners, their runs, influence, captures, friendships, challenges, races and
ghosts, then recomputes every territory they touched. The live world is left as
it was found.

## Time control

A challenge runs for days, which no one can sit through.
`POST /v1/admin/sandbox/challenges/{id}/fast-forward` shifts the whole window
into the past and settles it. The window ends *now* rather than a second ago, so
runs the operator has just added still count — an earlier version ended it a
second early and silently scored nothing.

Races age out the same way, to check that abandoning one lapses quietly.

## Synthetic runs

`POST /v1/admin/sandbox/runners/{id}/runs` writes an applied run straight to the
ledger, for scoring a challenge without driving it. It deliberately skips the
matching pipeline, so it creates no influence grants, no territory segments and
no captured areas. Geometry is therefore safe to attach — and is what makes a
run saveable as a ghost — while claiming nothing.

## The checklist

`admin/src/features/scenarios.ts` holds the scripted checks. Each creates its
own runners, drives the real API, and reports the failing assertion as a
sentence. They are mirrored server-side in `backend/tests/test_lab_scenarios.py`
so a change that breaks the lab fails in CI rather than in the console.

**The convention: a new feature means a new scenario.** A feature that cannot be
exercised from that list is not finished.

## Operator control of the map

Territory ownership is derived — `recompute_ownership` rebuilds it from the
influence ledger whenever a run lands there. An operator assigning a territory
therefore writes a **ledger grant** through a synthetic run rather than setting
the owner row, which a later run would silently revert. It is audited, and it is
durable for exactly the same reason a real capture is.

`POST /v1/admin/territory/{id}/assign` with no account clears the ledger for
that territory instead, returning it to unclaimed.

## Standings

`GET /v1/admin/territory/standings` lists territories that have contenders.
Most of a city has never been run through; the console's problem was never that
standings were missing but that you had to guess which of several hundred
territories had any.

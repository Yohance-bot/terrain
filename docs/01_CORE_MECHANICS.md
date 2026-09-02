# 01 — Core Mechanics

**Status:** Stable Draft v2

**Supersedes:** v1 (Stable Draft v1). Where the two disagree, this document wins.

---

## Purpose

The Project Vision explains *why* the game exists. This document explains *how it functions*.

Every gameplay system added in future must be compatible with the mechanics defined here. New features may expand the game. They should never contradict it.

This document defines gameplay, not implementation. It deliberately avoids databases, APIs and frontend architecture. Where a mechanic constrains implementation, that constraint is stated as a requirement, not as a design.

Related documents:

- `00_PROJECT_VISION` — why the project exists
- `02_WHAT_WE_REFUSE_TO_BECOME` — the product boundaries we will not cross
- `03_MAP_AND_TERRITORY_PIPELINE` — where territories come from and how they are rendered
- `04_APPLICATION_ARCHITECTURE` — how movement is recorded
- `05_ANTICHEAT_AND_TRUST` — how movement is validated before it counts

---

## What Changed From v1

v1 described influence as permanent, capped daily, and allocated purely by distance. Review found that permanent influence combined with a hard daily cap makes territory ownership mathematically uncontestable: an incumbent and a challenger both gain the same maximum per day, so the gap between them can never close, and every territory is permanently allocated to whoever arrives first.

v2 resolves this. The changes:

| Area | v1 | v2 |
| --- | --- | --- |
| Influence lifetime | Permanent, never expires | Active Influence decays; a separate permanent Legacy record preserves history |
| Daily cap | Hard per-territory daily cap | Removed entirely. Replaced by diminishing returns against current standing |
| Club balance | Club shares a cap equal to one player's | Removed. Diminishing returns, decay and Personal Record mode are tested first |
| Ownership | Highest influence | Highest Active Influence, no share threshold — plus an absolute inactivity floor that releases abandoned territories |
| Effort | Distance only | Distance, time and activity type |
| Territory coverage | Undefined | Territories exhaustively tile the city |
| Ownership subject | Undefined | A club, when the contributor runs for a club; otherwise the individual |

---

## What Is Built First

This document describes the complete system. It is not all built at once. Sequencing lives in `07_ROADMAP_AND_LAUNCH`; the summary is here so that a reader knows which mechanics are load-bearing for the first release.

| Mechanic | Phase 1 | Reason |
| --- | --- | --- |
| Influence, decay, diminishing returns, ownership | Yes | This is the loop. Nothing can be tested without it. |
| Territories, Home Territory | Yes | The board, and the player's anchor to it. |
| XP, levels, Prestige, streaks | Yes | Cheap, and they carry the sessions where nothing territorial happened. |
| Legacy | Yes | Costs almost nothing if the ledger is right, and cannot be reconstructed later. |
| Momentum | Deferred | Its job is balancing solo players against clubs. There are no clubs in Phase 1, so it has no job yet. |
| Clubs | Phase 2 | The most complex system in the document, and it should be built on a loop that has been proven to retain people. |
| Seasons, Coins, Missions, Checkpoints | Phase 2+ | None of them affect whether the core loop works, which is the only question Phase 1 asks. |

Deferring a mechanic does not mean deferring its schema. Legacy, club attribution and territory versioning must exist in the data model from the first migration even where the feature does not ship, because backfilling them is expensive and in some cases impossible.

---

## Core Gameplay Philosophy

The world is persistent. Movement changes it. Players compete by contributing more to places that matter.

The game should never ask players to "play the game." Gameplay should emerge from real movement.

Running is gameplay. Walking is gameplay. Exploring the city is gameplay.

---

## Design Pillars

**1. Movement changes the world.** No energy, no attack buttons, no stamina. Physically moving through the real world directly changes the shared game world. The less abstraction between movement and consequence, the better.

**2. Places matter.** Territories represent real places — parks, neighbourhoods, markets, lakes, campuses. Players should remember stories attached to places, not coordinates.

**3. Strategy comes from choice.** The game never asks how much you ran. It asks where you decided to run.

**4. Competition rewards consistency.** Winning should rarely come from one extraordinary effort. Ownership emerges from repeated contribution, and is kept only by continuing to show up.

**5. Simplicity creates depth.** Territory ownership must be explainable in one sentence: *run in a place to build influence there; whoever has the most influence right now owns it.*

---

## Chapter 1 — The Core Loop

```
Move
  ↓
The route is recorded
  ↓
The route is validated as real movement          (see 05_ANTICHEAT_AND_TRUST)
  ↓
The route is matched against territories          (territories tile the city exhaustively)
  ↓
Effort inside each territory becomes influence
  ↓
Territory ownership may change
  ↓
The player earns XP, Prestige and Legacy
  ↓
The world is now slightly different
  ↓
Move again
```

No manual claiming. No attack button. No spending influence. Movement itself changes the map.

The emotional centrepiece of this loop is the moment *after* the run, not during it. See Chapter 9.

---

## Chapter 2 — Influence

Influence is the foundation of the game. Everything else exists to support it.

### Two Ledgers

Influence is recorded twice, for two different purposes. They must never be conflated.

**Active Influence** determines who owns a territory right now. It is built by running there and it decays over time. It answers: *who controls this place today?*

**Legacy** is a permanent historical record of contribution to a place — total distance, days present, runs completed, days held, longest reign. It never decays and it never affects ownership. It answers: *who has this place belonged to, over the years?*

This split exists to satisfy two commitments that would otherwise contradict each other. The Vision requires that every run leaves a permanent mark; Legacy provides it. The refusal document requires that taking a break must not destroy months of progress, and that early players must not lock the world; decaying Active Influence provides that.

A player should be able to say *"I own Cubbon Park right now."* Another player should be able to see *"this person has held Cubbon Park for eight of the last twelve months."* Both are true statements about different things.

### Influence Is Local

Influence exists only inside the territory where it was earned. It cannot be moved, stored, or manually allocated. Every territory maintains its own independent standing.

### Influence Is Shown As A Share

A territory's standing is displayed as a percentage share of all Active Influence currently held there.

```
Cubbon Park

Adithya       42%
Sarah         37%
Rahul         14%
Emily          7%
```

A share is a ratio of accumulated standing, not a ratio of yesterday's distance. On a single day with no prior history, running 8 km against someone's 2 km does give 80% against 20%. Over time the numbers reflect accumulated, decayed contribution rather than any one run — which is what makes consistency, rather than a single long effort, the thing that wins.

Because shares are relative, a player's percentage changes when other people run even if that player does nothing. This is intended: it is the mechanism by which missing a day costs you ground. The interface must present this as *others gained*, never as *you lost* — the difference matters, and it is a requirement, not a preference.

### How A Run Becomes Influence

1. The route is validated as genuine movement.
2. The route is split by territory. Distance and moving time inside each territory are measured.
3. Segments below the **minimum presence threshold** are discarded — a player must actually have been in a place, not merely have crossed a corner of it.
4. Remaining segments are converted to **effort** (Chapter 3).
5. Effort is converted to Active Influence, reduced by **diminishing returns** based on the contributor's current share of that territory.
6. Standings and ownership are recalculated.

The player never chooses where influence goes. The game decides entirely from where movement actually occurred.

### Diminishing Returns

The closer a contributor is to holding a territory outright, the less each additional kilometre there is worth.

```
influence gained  =  effort  ×  (1 − current share) ^ γ
```

At a 0% share, a run is worth its full effort. At 50%, half. At 90%, a tenth. `γ` is a tuning constant; `γ = 1` is the starting assumption.

This single rule replaces the entire v1 cap system. It does the same job — preventing infinite farming of one location — without the fatal side effect. Under a hard cap, all effort past the cap was worth exactly zero, which made every other modifier in the game meaningless for engaged players. Under diminishing returns, effort is always worth something, but the marginal value of the sixth kilometre in a place you already dominate is small enough that running somewhere else is usually the better decision. Strategy comes from that trade-off.

**The balancing property this produces.** With `γ = 1`, when contributions and decay reach equilibrium, the ratio of two contributors' standings settles at the *square root* of the ratio of their efforts. Four times the effort yields twice the standing. Twenty times the effort yields about four and a half times the standing, or roughly 82% against 18%.

This is the most important consequence in the whole system and it should be understood before any balancing decision is made: **effort matters, but it is heavily compressed.** A player who runs twice as much as you does not end up twice as far ahead. This is what makes it possible for an ordinary consistent runner to stay competitive with a fanatic, and it is why no explicit cap is needed.

### Decay

Active Influence decays continuously, on an exponential curve, described by a **half-life** per territory.

**Exponential decay, not a rolling cutoff.** A fixed window — "active influence is the sum of the last 90 days" — is rejected. It creates a cliff: on day 89 a contribution counts fully and on day 91 it is worth nothing, and a player can lose a territory to arithmetic that has nothing to do with anything they or their rival did that week. Exponential decay makes every day slightly less valuable than the one before it, which is both fairer and easier to feel. Nothing ever falls off.

This does not complicate storage. A daily rollup per player, territory and day serves both ledgers: Active Influence is that rollup weighted by age, Legacy is the same rollup summed unweighted.

A 21-day half-life means a missed day costs roughly 3% of your standing in that place, a missed week roughly 20%, and a two-week holiday roughly 37% — all recoverable within about a week of returning to normal activity. Slower half-lives make the world more stable and less responsive; faster ones make it more volatile and more anxious. This constant is the single most important number in the game and it must be tuned from real play, not from theory.

Decay is what makes the world contestable, what makes defence meaningful, and what prevents any territory from ever being permanently locked.

### Ownership

**The owner of a territory is whoever holds the highest Active Influence share. There is no minimum threshold.**

42% beats 41%. Competition is about taking the lead, not about clearing an arbitrary bar. A neutral or unclaimed state triggered by closeness would be frustrating precisely in the most competitive places, which is where the game should feel best.

Ownership changes automatically and immediately when the lead changes. There are no battles, no health bars, no attack buttons. Movement is the competition.

### Abandonment

There is no minimum *share* required to own a territory, and there never will be. There is a minimum *absolute* amount of Active Influence required for a territory to be owned by anyone at all.

Because decay is exponential it never reaches zero. Without this rule, a territory nobody has visited in a year would stay permanently attached to whoever last passed through it, on a vanishing quantity of influence. That is a different problem from close competition and it takes a different answer.

**If the total Active Influence remaining in a territory falls below an absolute floor, the territory becomes unclaimed until someone contributes meaningfully again.**

The rule applies to the territory's total, not to the leader's holding. Applying it to the leader alone would simply hand ownership to the second-place player on even less influence, which is worse than having no owner.

This is emphatically not a neutral state produced by close competition. Nothing about who is winning can trigger it. A player actively defending a place remains its owner whether they hold 40% or 55%. Only prolonged and total inactivity — by everyone — releases a territory. Its purpose is to stop abandoned places being permanently attached to accounts that no longer play, not to introduce ambiguity into a live contest.

---

## Chapter 3 — Effort

Distance alone is not enough. It would make a walked kilometre identical to a run kilometre, contradicting the Vision's statement that running should generally be more efficient, and it would quietly exclude the recovering, the elderly and the slow — exactly the people the Vision explicitly names.

Effort is therefore derived from three inputs:

- **Distance** covered inside the territory
- **Moving time** spent inside the territory
- **Activity type** — walking or running, distinguished by pace

```
effort  =  activity weight  ×  ( wd × distance  +  wt × moving time )
```

Pace is used *only* to classify the activity as walking or running. It is never used to reward speed beyond that. A fast runner covers more distance in the same time and is rewarded through distance; they are not additionally rewarded for being fast.

The intended outcome: running is generally more efficient per hour than walking, walking is never worthless, and a slower runner is never meaningfully punished for being slower.

Activity classification, the weights, and the walking multiplier are all tuning constants. Cycling and other wheeled activity are **out of scope permanently** — they are not supported, not imported, and not converted.

### Minimum Presence

A segment generates influence only if it exceeds a minimum distance *and* a minimum moving time inside that territory.

The purpose is to stop players from harvesting influence by clipping the corner of a territory or by running along a boundary to touch many territories cheaply. With territories exhaustively tiling the city, boundaries are everywhere, and without this rule the optimal route is a border-hugging one — which would also push players onto exactly the arterial roads that are least safe to run on.

The threshold is a tuning constant. A starting proposal is 150 metres and 60 seconds.

The second and more effective defence against this is geographic, not mechanical: territory boundaries should follow features people do not run along. See `03_MAP_AND_TERRITORY_PIPELINE`.

---

## Chapter 4 — Territory Character

Territories are not interchangeable. Each has its own character, assigned when the city is generated and reviewed by a human before publication.

### Geography Creates Gameplay

Territory geography is not decoration. The physical characteristics of a place determine how it plays.

Cubbon Park has a large runnable area, high foot traffic, and historical importance in the city. That geography naturally produces:

high prestige
many competitors
slower decay
a place that is hard to win and meaningful to hold

A small residential neighbourhood has less traffic, fewer competitors, and less prestige. That geography naturally produces:

easier ownership for a new player
faster change of hands
a place that serves as the on-ramp to the game

The generation pipeline reads geography and assigns gameplay parameters from it — influence capacity from runnable path length, decay half-life from strategic importance, prestige weighting from landmark status. Geography should create gameplay naturally rather than arbitrary numbers being applied to identical polygons.

See `03_MAP_AND_TERRITORY_PIPELINE` for how these parameters are assigned during generation and review.

| Property | Effect |
| --- | --- |
| **Influence capacity** | How much accumulated influence a territory naturally holds. Scales with the amount of runnable path inside it, not with raw area. |
| **Decay half-life** | How quickly Active Influence fades here. |
| **Strategic value** | Prestige weighting. Feeds Prestige and Legacy, not ownership. |
| **Difficulty** | A derived summary of the above, shown to players. |

The intended feel:

**A landmark — Cubbon Park, Lalbagh, Ulsoor Lake.** Large running area, high traffic, many competitors, slow decay, high prestige. Hard to win because many people want it. Once won, it does not slip away overnight. Holding one is a statement.

**A small neighbourhood.** Modest running area, few competitors, faster decay, low prestige. Easy to take, easy to lose, changes hands often.

A new player must realistically be able to claim their own local area. This is where a first taste of ownership happens, in the first week, close to home, without competing with anyone famous. It is the on-ramp to everything else and it should be designed as one.

### Why Landmarks Decay Slower

The reason is emotional, not protective.

If a landmark changed hands every few days, holding one would mean nothing. A player should be able to say *"I held Cubbon Park for six months"* and have that be a true statement about six months of showing up. Slow decay is what gives long tenure its weight.

It is not there to shelter the current owner.

> **Landmarks must be difficult because many people want them, never because the system protects whoever currently holds them.**

The spread must therefore stay controlled. Starting range: roughly a 14-day half-life for small local territories and 28 days for major landmarks. This is a tuning range, not a fixed rule, and the correct values come from play.

If a landmark ever becomes effectively impossible to challenge, the spread is wrong. It is not the challenger's problem to solve.

The two-ledger split already handles the thing slow decay might otherwise be asked to do: Legacy preserves former champions permanently, so Active Influence is free to stay contestable. Decay differences add character. They must never create permanence.

---

## Chapter 5 — Home Territory

Every player chooses one territory as their **Home** during onboarding.

Home is the personal anchor of the entire product. The core fantasy is *"this is my place"*, and without a designated one, a new player opens the map and sees a city that belongs to strangers. Home makes the first question the game asks a small and answerable one.

### What Home Is

Home is **where you are from**, not what you own.

This distinction is deliberate and it is the source of most of Home's emotional value. A player's Home is Koramangala whether or not they currently control Koramangala. If someone else holds it, the game is not telling them they have failed — it is telling them there is something to take back. *"Someone else owns my neighbourhood"* is a far better motivator than an empty map.

A player's profile shows their Home, how long they have held it if they do, and what they have permanently contributed to it.

```
Adithya

Home            Koramangala
Currently       Held by you, 42 days
Legacy          87 km contributed, 3rd longest reign
```

### Why It Exists

**It solves the cold-start problem.** A new player joining a city where landmarks are already contested does not have to compete for Cubbon Park on day one. They have a nearby, low-traffic, quickly-changing territory and a single clear instruction: hold your neighbourhood. `01`'s territory character design already makes small local territories the natural on-ramp; Home is what points a player at theirs.

**It gives every player a stake.** Territory a player has no attachment to is just a coloured polygon. Home converts an abstract map into a personal one from the first session.

**It creates the defender fantasy.** Attacking is easy to design and defending is not. Home is what makes losing something feel like losing something.

### Rules

- Exactly one Home per player.
- Chosen during onboarding, from territories near the player's actual location.
- Changeable, subject to a cooldown, so Home cannot be hopped to wherever is momentarily convenient.
- Home confers a modest, bounded bonus to influence earned inside it. Enough to make defending home meaningfully easier than attacking someone else's; never enough to make a home territory uncontestable by an outsider who genuinely commits to it.
- Home never confers ownership. It is an attachment, not a claim.

> **Open question — the home bonus.** Its size is undetermined and it carries real risk in both directions. Too small and Home is decoration. Too large and every territory becomes permanently owned by whoever declared it home first, which is the seniority problem returning through a side door. Start small, and treat any home territory that has never changed hands as evidence the bonus is too high.

---

## Chapter 6 — Clubs

**Phase 2.** Designed here in full, built after the core loop has demonstrated retention. Clubs are the most complex system in this document and the least reversible if built on a loop that turns out not to work. The schema must nevertheless carry club attribution from the first migration.

Clubs create social competition and let a group hold places no individual could hold alone.

### Ownership Attribution

A run made on behalf of a club contributes to the club's Active Influence in the territories it crosses. **When a club leads a territory, the club is the owner.** The individual who pushed it over the line is credited and displayed — *"captured by Adithya"* — but the place belongs to the club.

Every run, regardless of mode, also contributes to the runner's personal Legacy, XP, Prestige, streaks and statistics. Joining a club never costs a runner their personal history.

### Personal Record Mode

A club member may switch any individual run into **Personal Record mode**, in which that run's influence goes to the player rather than the club.

This is not a convenience feature. It is the release valve for the saturation problem that diminishing returns necessarily create.

When a club already dominates a territory, each additional club run there is worth very little. Without an alternative, a member would rightly feel *"my run was meaningless, my club already owns this place."* That feeling is unacceptable — it is the exact opposite of the emotional loop the product exists to produce.

With the toggle, that player has a real choice on every run:

- **Club mode** — contribute toward the shared club territory.
- **Personal Record mode** — build a personal claim and a personal ownership story.

So a saturated territory does not waste effort; it redirects it. The system leaks contribution away from places that are already decided, by design.

It also means joining a club is never a downgrade for a strong runner. A committed player can support the club most of the time and still hold the places that matter to them personally.

> Clubs should amplify social competition, never erase individual competition.

The default mode, and how prominently the toggle is surfaced, are UX decisions belonging to `04_APPLICATION_ARCHITECTURE`.

### One Club At A Time

A player belongs to exactly one club. Switching is allowed, subject to a cooldown.

This prevents a player from multiplying their contribution across clubs, gives clubs a real identity, and makes club rivalry mean something.

### Leaving A Club

Contribution already made stays with the club. Influence a departing member built is not withdrawn, and history is not rewritten. A club's standing reflects what the club did, not who currently happens to be a member.

### One Shared Contest

There is no separate club leaderboard, no parallel club ownership layer, and no split contest. A club and an individual compete for the same territory, in the same standing, on the same map.

This is a product decision, not a balance decision, and it does not bend to balance arguments. The central fantasy depends on it. *"Our club owns this park"* and *"one runner took his neighbourhood back from a five-hundred-person club"* are the same system producing two different stories, and the second becomes impossible the moment the contests are separated.

A solo runner must always retain a real path to defeating a club through sustained dedication. That story is one of the strongest outcomes the system can produce and it is worth protecting at some cost elsewhere.

### No Club Cap

v1 gave each club a shared cap equal to one individual's. Removed. It was an artificial limit imposed before the natural balance of the system was understood.

A five-hundred-member club **should** feel powerful — provided five hundred people are actually out running and defending. The goal is not to stop clubs being strong. It is to ensure their strength comes from continued participation rather than from historical ownership. Three mechanisms already enforce exactly that:

- **Diminishing returns** — the more a contributor already holds, the less each run adds.
- **Decay** — no group can lock a place. They have to keep showing up.
- **Territory character** — a landmark with many competitors behaves nothing like a quiet neighbourhood.

### The Known Asymmetry

Stated plainly so it is monitored rather than forgotten.

Under diminishing returns alone, a club of twenty runners all sustaining effort on the same territory settles at roughly 82% against a comparable solo player's 18%. The system's square-root compression turns twenty times the effort into about four and a half times the standing — a large reduction, but four and a half times is still decisive. Momentum does not close that gap.

This is knowingly accepted for now. Three things are expected to make it survivable in practice, and they are the reason no further control is being added pre-emptively:

1. **Decay punishes drift.** A club's hold is only as good as its current attention. When a club's focus moves elsewhere in the city — and it will — its grip erodes while one consistent runner's does not. That is precisely the story the design wants to be possible.
2. **Saturation redirects effort.** As a club approaches domination, additional club contribution there approaches worthlessness, so its own members are pushed by the maths toward Personal Record mode or toward other territories. A club cannot easily concentrate indefinitely on one place, because the system stops paying it to.
3. **The 82/18 figure is a theoretical equilibrium.** It assumes twenty runners pointing sustained, undivided effort at one territory forever. Real clubs disperse, members lapse, and attention moves.

### What Would Change This Decision

So that the judgement is made on evidence rather than argument, the conditions for introducing club compression are stated in advance. If, across a full season in the launch corridor:

- landmark territories are club-held essentially all of the time, **and**
- no landmark changes hands from a club to an individual, **and**
- solo contribution in landmark territories measurably declines as players give up,

then club effort is compressed by the square root of active contributor count — a club of twenty behaving like roughly four and a half individuals, which after diminishing returns leaves it about twice as strong as a comparable solo runner rather than four and a half times.

Until all three conditions are observed together, no additional club control is added. One or two of them alone is not enough; players avoiding a place could equally mean the territory is badly sized.

---

## Chapter 7 — Momentum

Momentum rewards the runner who keeps showing up. A player who runs regularly and defends what they hold should feel measurably stronger in a direct contest than someone who appears occasionally.

Momentum is built by consistent activity over consecutive days and is bounded by a ceiling, so it can never compound into an insurmountable advantage.

**What momentum does:** it strengthens a player in direct competition — making their contribution more effective, their standing more resistant to decay, or both. The precise mechanism is a tuning decision to be made against real play. It explicitly does **not** simply help a player reach a limit faster; there is no limit to reach.

**Momentum decays, it does not reset.** Missing a day costs a little. Missing a week costs more. Nothing is ever wiped. A single missed day must never feel like a punishment, and no player should ever feel they must run today to avoid losing something they built over months.

**Momentum applies to individual competition only.** A club member builds momentum normally and it benefits their personal standing and Personal Record runs. It does not multiply the club's influence. One exceptionally consistent runner should have an edge when fighting alone; they should not make their club unbeatable.

---

## Chapter 8 — Progression

Four distinct records, deliberately separated. Each answers a different question.

| System | Question it answers | Decays | Affects ownership |
| --- | --- | --- | --- |
| **Active Influence** | Who controls this place right now? | Yes | Yes |
| **Legacy** | Who has this place belonged to, historically? | No | No |
| **XP** | How much running has this person done? | No | No |
| **Prestige** | How respected is this runner overall? | No | No |

**XP** measures running consistency and volume and drives a runner level. It accumulates from every recorded activity regardless of where it happened, including activity that generates no influence at all. A player who runs frequently naturally levels up. This is the progression that never lets a session feel wasted.

**Prestige** is a reputation score combining influence held, history, and consistency. It is how the game says *this person is a serious runner* without reducing them to a single leaderboard position.

> **Open question — formulas.** The exact composition of Prestige, the XP curve, and what if anything a runner level unlocks are all undesigned. Nothing may gate access to gameplay behind level; progression is expression, not permission.

### Coins

A soft currency, earned through play, deferred to a later phase.

Coins are **not power**. The rule is absolute and follows directly from `02_WHAT_WE_REFUSE_TO_BECOME`:

| Coins may buy | Coins may never buy |
| --- | --- |
| Cosmetics | Influence, or anything that generates it |
| Profile badges and banners | Territory protection or defence |
| Map styling and effects | Decay resistance |
| Celebration and reveal effects | Momentum, XP or Prestige |

Two constraints that must be honoured from the moment Coins exist, not retrofitted:

**Coins are never redeemable for money** and must never be described in language that could be read as redeemable. India's gaming and payments regulation treats convertibility as the line between a game currency and a financial product, and the wrong marketing copy is enough to cross it.

**Coins are never purchasable with money in a way that shortcuts movement.** Whether real money can buy Coins at all is an open question; if it ever can, everything Coins buy must remain purely cosmetic, so that money buys appearance and only movement buys standing.

### Missions

Short, rotating objectives — visit three territories today, run two kilometres in your Home, reach a place you have never been.

Their purpose is to answer a specific failure: a player in a quiet part of the city opens the app and finds that nothing changed, because nobody contested anything near them. Missions manufacture a reason to move on days when the world does not supply one.

Deferred to a later phase, deliberately. The core loop has to work on its own first. If players only run because a mission told them to, the loop has failed and missions will hide that failure rather than fix it.

Missions must never create urgency or guilt. Nothing expires in a way that punishes, nothing counts down, and a missed mission costs nothing.

---

## Chapter 9 — Seasons

Seasons exist to refresh competition periodically without erasing identity.

> **Open question — everything about them.** Agreed in principle, undesigned in specifics. What resets (competitive standing), what survives (Legacy, XP, Prestige, club membership, ownership history), how long a season runs, and whether seasons are global or per-city are all unresolved. Nothing about seasons should be built until the base loop has been observed in real play, because season length is a retention decision that requires retention data.

---

## Chapter 10 — The Post-Run Reveal

The most important screen in the product.

The application should not distract from running. Territory information is deliberately withheld during activity. The emotional payload is delivered once, afterwards, when the player is standing still and safe.

The feeling being engineered is *"I wonder what changed."*

After a run, the player learns:

- Where their influence grew, and by how much
- Whether they took, lost, defended or approached ownership anywhere
- Who they are now competing against, and how close it is
- What their club gained or defended
- What their run added to their permanent record in those places

Ordinary running metrics — distance, time, pace, route, splits, personal statistics — are recorded and shown as any running app would show them. Those are the reason a player trusts the app enough to record with it. The territory reveal is the reason they came back.

The map is not the product. The feeling of having changed the map is the product.

---

## Chapter 11 — Checkpoints

Checkpoints are a **reserved concept**. They exist in the spatial model as named point locations inside territories, and they are intended to support sponsored locations, local events, and community challenges — a café, a water refill station, an event start line, a charity stop.

No checkpoint mechanic is defined, and none should be implemented until one is designed. They are named here only so that the spatial pipeline can carry them and the term means one thing across documents.

---

## Chapter 12 — What This System Deliberately Does Not Do

- **No daily cap.** Removed in v2. Effort is always worth something.
- **No neutral or contested ownership state** based on closeness. The leader owns it. The only way a territory becomes unclaimed is total abandonment by everyone.
- **No separate club leaderboard or club ownership layer.** One shared contest, always.
- **No manual claiming, no attack action, no spending of influence.** Movement is the only verb.
- **No influence transfer between places.** Influence is local, permanently.
- **No purchasable advantage.** Nothing in this document may ever be bought.
- **No cycling or wheeled activity.** Permanently out of scope.
- **No reward for imported third-party activity.** Imported runs may inform personal statistics; they never generate influence. See `05_ANTICHEAT_AND_TRUST`.
- **No real-time territory feedback during a run.** Safety and focus both require this.

---

## Tuning Constants

Every number in this document is provisional and must be set from observed play, not from theory. Consolidated here so no constant is ever hardcoded in prose elsewhere.

| Constant | Symbol | Starting proposal |
| --- | --- | --- |
| Decay half-life, small territory | H | 14 days |
| Decay half-life, landmark territory | H | 28 days |
| Territory inactivity floor | — | Undetermined |
| Diminishing returns exponent | γ | 1.0 |
| Minimum presence, distance | — | 150 m |
| Minimum presence, time | — | 60 s |
| Walking activity weight | — | ~0.7 of running |
| Distance / time weighting | wd, wt | Undetermined |
| Momentum ceiling | — | Undetermined |
| Days of consistency to reach maximum momentum | — | 14–21 days |
| Club switch cooldown | — | 14 days |
| Home territory bonus | — | Small; undetermined |
| Home territory change cooldown | — | 30 days |

---

## Open Design Questions

Carried forward deliberately. Each is named so it is a known gap rather than a surprise.

1. **Home territory bonus size.** Too small and Home is decoration; too large and it recreates the seniority problem. See Chapter 5.
2. **Momentum mechanism.** Whether momentum strengthens contribution, resists decay, or both — and its ceiling.
3. **Personal Record mode defaults.** Whether club runs default to club mode, and how visible the toggle is.
4. **Prestige and XP formulas**, and whether runner level unlocks anything.
5. **Coins.** Whether real money may ever buy them, and what they cost.
6. **Seasons.** What resets, what survives, how long, global or per-city.
7. **Checkpoint mechanics.** Entirely undesigned.
8. **Territory boundary regeneration.** How accumulated influence migrates when a territory's shape is corrected after launch. Owned by `03_MAP_AND_TERRITORY_PIPELINE`, but it affects influence, so it is listed here too.
9. **All tuning constants above**, including the inactivity floor and the decay half-life range.

### Decided, but monitored

Not open questions. Resolved with a stated condition for revisiting.

- **Club compression.** Deferred pending evidence. The three conditions that would trigger it are defined in Chapter 5 and must be instrumented from the first season, otherwise the decision cannot be made.
- **Decay half-life spread.** 14 to 28 days as a starting range. Revisit if landmarks become effectively unchallengeable.
- **Abandonment floor.** Decided in principle; the value is a tuning constant.

---

## Compatibility Rule

Any future mechanic must satisfy all of the following, or it does not belong in the product:

1. It is driven by real physical movement.
2. It cannot be purchased.
3. It does not make the world permanently unwinnable for someone who joins later.
4. It does not punish a player for resting, travelling, or living their life.
5. It does not require the player to look at their phone while moving.
6. It works for a walker, not only for a runner.
7. It keeps individuals and clubs competing in one shared ownership system.
8. It leaves a committed individual a real path to victory against any group.
9. It remains explainable in one sentence.

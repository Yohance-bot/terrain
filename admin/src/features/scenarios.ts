import { api, asRunner, request, type TestRunner } from "../lib/api";

/**
 * The feature checklist, as runnable scripts.
 *
 * Each scenario creates its own runners and drives the real player API through
 * minted sessions, so a pass here means the same call sequence works on the
 * phone. Every scenario is independent and leaves nothing behind that another
 * one depends on.
 *
 * ADDING A FEATURE: add a scenario. That is the whole convention — a feature
 * that cannot be exercised from this list is not finished.
 */

export type ScenarioContext = {
  /** Create a fresh runner for this scenario. Torn down with the lab. */
  runner: (label: string) => Promise<TestRunner>;
  log: (message: string) => void;
};

export type Scenario = {
  id: string;
  title: string;
  covers: string;
  run: (context: ScenarioContext) => Promise<void>;
};

export type ScenarioOutcome = {
  status: "pending" | "running" | "passed" | "failed";
  detail?: string;
  steps: string[];
  ms?: number;
};

/** A failed check reads as a sentence, because that is what gets shown. */
function check(condition: unknown, message: string): asserts condition {
  if (!condition) throw new Error(message);
}

const BENGALURU = { lon: 77.5946, lat: 12.9716 };
/** Far enough from the pin to not count as an arrival. */
const AWAY = { lat: 12.9716, lon: 77.5946 };

async function friends(first: TestRunner, second: TestRunner) {
  await asRunner(first, "/social/friends/requests", {
    method: "POST",
    body: JSON.stringify({ handle: second.handle }),
  });
  const incoming = await asRunner<any>(second, "/social/friends");
  const request = incoming.incoming[0];
  check(request, `${second.display_name} never received the friend request`);
  await asRunner(second, `/social/friends/requests/${request.id}/accept`, {
    method: "POST",
  });
}

async function position(runner: TestRunner, lat: number, lon: number, running = true) {
  return asRunner<any>(runner, "/social/position", {
    method: "POST",
    body: JSON.stringify({ lat, lon, is_running: running }),
  });
}

export const SCENARIOS: Scenario[] = [
  {
    id: "identity",
    title: "A new account gets a findable handle",
    covers: "Accounts · handles · search",
    run: async ({ runner, log }) => {
      const first = await runner("Identity A");
      const second = await runner("Identity B");
      check(first.handle, "The new account was not given a handle");
      log(`Handle assigned: @${first.handle}`);

      const found = await asRunner<any[]>(
        second,
        `/social/search?q=${encodeURIComponent(first.handle)}`,
      );
      check(
        found.some((row) => row.id === first.account_id),
        "Searching the exact handle did not find the account",
      );
      check(found[0].relationship === "none", "A stranger should read as 'none'");

      const byId = await asRunner<any[]>(second, `/social/search?q=${first.account_id}`);
      check(byId.length === 1, "Searching by account ID did not find exactly one account");
      log("Found by handle and by account ID");
    },
  },
  {
    id: "friends",
    title: "A friend request can be sent and accepted",
    covers: "Friend requests",
    run: async ({ runner, log }) => {
      const first = await runner("Friend A");
      const second = await runner("Friend B");

      await asRunner(first, "/social/friends/requests", {
        method: "POST",
        body: JSON.stringify({ handle: second.handle }),
      });
      const pending = await asRunner<any>(second, "/social/friends");
      check(pending.incoming.length === 1, "The request did not arrive");
      log("Request received");

      await asRunner(second, `/social/friends/requests/${pending.incoming[0].id}/accept`, {
        method: "POST",
      });
      for (const [who, other] of [
        [first, second],
        [second, first],
      ] as const) {
        const list = await asRunner<any>(who, "/social/friends");
        check(
          list.friends.some((row: any) => row.account.id === other.account_id),
          `${who.display_name} does not see ${other.display_name} as a friend`,
        );
      }
      log("Both sides are friends");
    },
  },
  {
    id: "blocking",
    title: "A block hides an account and cannot be detected",
    covers: "Blocking · anti-harassment",
    run: async ({ runner, log }) => {
      const blocker = await runner("Blocker");
      const blocked = await runner("Blocked");

      await asRunner(blocker, `/social/block/${blocked.account_id}`, { method: "POST" });
      const search = await asRunner<any[]>(
        blocked,
        `/social/search?q=${encodeURIComponent(blocker.handle)}`,
      );
      check(search.length === 0, "A blocked account is still findable");

      let detail = "";
      try {
        await asRunner(blocked, "/social/friends/requests", {
          method: "POST",
          body: JSON.stringify({ handle: blocker.handle }),
        });
        throw new Error("Requesting a blocker should fail");
      } catch (error) {
        detail = (error as Error).message;
      }
      check(
        detail.includes("No account matches"),
        `A block must look like a missing account, but the error was: ${detail}`,
      );
      log("Block is indistinguishable from 'no such account'");

      await asRunner(blocker, `/social/block/${blocked.account_id}`, { method: "DELETE" });
      log("Unblocked");
    },
  },
  {
    id: "sharing",
    title: "Location sharing is off until turned on, and off again instantly",
    covers: "Live location sharing",
    run: async ({ runner, log }) => {
      const runnerA = await runner("Sharer");
      const runnerB = await runner("Watcher");
      await friends(runnerA, runnerB);

      await position(runnerA, BENGALURU.lat, BENGALURU.lon);
      let live = await asRunner<any>(runnerB, "/social/live");
      check(live.friends.length === 0, "A friendship alone exposed a position");
      log("Friendship alone shares nothing");

      await asRunner(runnerA, `/social/sharing/${runnerB.account_id}`, {
        method: "PUT",
        body: JSON.stringify({ share_location: true }),
      });
      await position(runnerA, BENGALURU.lat, BENGALURU.lon);
      live = await asRunner<any>(runnerB, "/social/live");
      check(live.friends.length === 1, "Sharing was turned on but nothing is visible");
      log("Position visible after opting in");

      await asRunner(runnerA, `/social/sharing/${runnerB.account_id}`, {
        method: "PUT",
        body: JSON.stringify({ share_location: false }),
      });
      live = await asRunner<any>(runnerB, "/social/live");
      check(live.friends.length === 0, "Turning sharing off did not hide the position");
      log("Hidden again immediately");
    },
  },
  {
    id: "run-alerts",
    title: "Run-start alerts work without exposing location",
    covers: "Run-start notifications",
    run: async ({ runner, log }) => {
      const runnerA = await runner("Announcer");
      const runnerB = await runner("Listener");
      await friends(runnerA, runnerB);

      await asRunner(runnerA, `/social/sharing/${runnerB.account_id}`, {
        method: "PUT",
        body: JSON.stringify({ notify_on_run_start: true }),
      });
      await asRunner(runnerA, `/social/runs/${crypto.randomUUID()}/started`, {
        method: "POST",
      });
      await position(runnerA, BENGALURU.lat, BENGALURU.lon);

      const events = await asRunner<any[]>(runnerB, "/social/events");
      check(
        events.some((event) => event.kind === "run_started"),
        "The run-start alert never arrived",
      );
      const live = await asRunner<any>(runnerB, "/social/live");
      check(
        live.friends.length === 0,
        "A run-start alert leaked the runner's position — the toggles are not independent",
      );
      log("Alert delivered, position still private");
    },
  },
  {
    id: "challenge",
    title: "A challenge settles from the run ledger",
    covers: "Challenges · automatic resolution",
    run: async ({ runner, log }) => {
      const challenger = await runner("Challenger");
      const opponent = await runner("Opponent");
      await friends(challenger, opponent);

      const challenge = await asRunner<any>(challenger, "/social/challenges", {
        method: "POST",
        body: JSON.stringify({
          opponent_id: opponent.account_id,
          metric: "distance",
          comparison: "most",
          window_days: 3,
          goal_text: "Most distance over three days",
        }),
      });
      await asRunner(opponent, `/social/challenges/${challenge.id}/accept`, { method: "POST" });
      log("Challenge accepted, window started");

      await api.addSyntheticRun(challenger.account_id, 3000);
      await api.addSyntheticRun(opponent.account_id, 9000);
      const settled = await api.fastForwardChallenge(challenge.id);
      check(settled.resolved >= 1, "Fast-forwarding settled nothing");

      const list = await asRunner<any[]>(challenger, "/social/challenges");
      const resolved = list.find((row) => row.id === challenge.id);
      check(resolved?.status === "resolved", "The challenge did not resolve");
      check(
        resolved.winner_id === opponent.account_id,
        `The wrong side won: expected the runner who covered 9 km`,
      );
      log("Resolved to the runner who covered more ground");
    },
  },
  {
    id: "race",
    title: "Reaching the pin wins a race and ends the sharing it granted",
    covers: "Spontaneous races · proximity arrival",
    run: async ({ runner, log }) => {
      const first = await runner("Pin Dropper");
      const second = await runner("Sprinter");
      await friends(first, second);

      const pin = { pin_lat: 12.98, pin_lon: 77.6 };
      const race = await asRunner<any>(first, "/social/races", {
        method: "POST",
        body: JSON.stringify({ opponent_id: second.account_id, ...pin, pin_label: "Lab pin" }),
      });
      await asRunner(second, `/social/races/${race.id}/accept`, { method: "POST" });
      log("Race accepted");

      await position(first, AWAY.lat, AWAY.lon);
      const seen = await asRunner<any>(second, "/social/live");
      check(
        seen.friends.some((row: any) => row.account.id === first.account_id),
        "A running race did not grant mutual visibility",
      );
      check(seen.races.length === 1, "The live view does not carry the running race");

      // Fifteen metres from the pin: inside the forgiving arrival radius.
      await position(second, pin.pin_lat + 0.00013, pin.pin_lon);
      const races = await asRunner<any[]>(second, "/social/races");
      const finished = races.find((row) => row.id === race.id);
      check(finished?.status === "finished", "Arriving at the pin did not finish the race");
      check(finished.winner_id === second.account_id, "The wrong runner won the race");
      log("Arrival detected from an ordinary position report");

      const after = await asRunner<any>(second, "/social/live");
      check(
        after.friends.length === 0,
        "Race sharing outlived the race — a temporary grant must end with it",
      );
      log("Temporary sharing revoked");
    },
  },
  {
    id: "race-expiry",
    title: "An abandoned race lapses without declaring a loser",
    covers: "Races · quiet expiry",
    run: async ({ runner, log }) => {
      const first = await runner("Starts A Race");
      const second = await runner("Wanders Off");
      await friends(first, second);

      const race = await asRunner<any>(first, "/social/races", {
        method: "POST",
        body: JSON.stringify({ opponent_id: second.account_id, pin_lat: 12.98, pin_lon: 77.6 }),
      });
      await asRunner(second, `/social/races/${race.id}/accept`, { method: "POST" });
      await api.fastForwardRace(race.id);

      const races = await asRunner<any[]>(second, "/social/races");
      const lapsed = races.find((row) => row.id === race.id);
      check(lapsed?.status === "expired", "An abandoned race did not expire");
      check(lapsed.winner_id === null, "An expired race must not have a winner");

      const events = await asRunner<any[]>(second, "/social/events");
      check(
        !events.some((event) => event.kind === "race_finished"),
        "Walking away from a race told someone they lost",
      );
      log("Lapsed quietly, nobody told they lost");
    },
  },
  {
    id: "ghost",
    title: "A broadcast ghost is raceable and hides where its runner started",
    covers: "Ghost runs · broadcast · privacy trim",
    run: async ({ runner, log }) => {
      const owner = await runner("Ghost Owner");
      const racer = await runner("Ghost Racer");

      // A ghost needs a real route, which a synthetic run only gets on request.
      const routed = await request<any>(
        `/admin/sandbox/runners/${owner.account_id}/runs`,
        {
          method: "POST",
          body: JSON.stringify({
            distance_m: 1200,
            duration_s: 600,
            route_lon: BENGALURU.lon,
            route_lat: BENGALURU.lat,
          }),
        },
      );
      check(routed?.run_id, "The lab could not create a run to save as a ghost");

      const ghost = await asRunner<any>(owner, "/social/ghosts", {
        method: "POST",
        body: JSON.stringify({
          run_id: routed.run_id,
          name: "Lab benchmark",
          is_public: true,
        }),
      });
      check(ghost.is_public, "The ghost was not broadcast");
      check(
        ghost.share_live_location === false,
        "Broadcasting a ghost must not also share the runner's live position",
      );
      log("Ghost broadcast, live position still private");

      const nearby = await asRunner<any[]>(
        racer,
        `/social/ghosts/nearby?lat=${BENGALURU.lat}&lon=${BENGALURU.lon}&radius_m=2000`,
      );
      check(
        nearby.some((row) => row.id === ghost.id),
        "A broadcast ghost is not discoverable nearby",
      );

      const mine = await asRunner<any>(owner, `/social/ghosts/${ghost.id}`);
      const theirs = await asRunner<any>(racer, `/social/ghosts/${ghost.id}`);
      check(
        theirs.path.length < mine.path.length,
        "A public ghost was served untrimmed — it exposes where its runner started",
      );
      log(`Route trimmed for strangers: ${mine.path.length} → ${theirs.path.length} points`);

      const attempt = await asRunner<any>(racer, `/social/ghosts/${ghost.id}/attempts`, {
        method: "POST",
      });
      const finished = await asRunner<any>(
        racer,
        `/social/ghosts/attempts/${attempt.id}/finish`,
        { method: "POST", body: JSON.stringify({ elapsed_s: ghost.duration_s - 60 }) },
      );
      check(finished.beat_ghost === true, "Finishing faster than the ghost did not count as a win");

      const still = await asRunner<any>(racer, `/social/ghosts/${ghost.id}`);
      check(still.id === ghost.id, "Racing a ghost consumed it — it must stay available");
      log("Ghost beaten and still available for the next person");
    },
  },
  {
    id: "athlete",
    title: "Runs become stats, a streak, records, a goal and shoe mileage",
    covers: "Athlete profile · training log · goals · shoes · friend profile",
    run: async ({ runner, log }) => {
      const athlete = await runner("Athlete");
      const friend = await runner("Athlete Friend");

      const shoe = await asRunner<any>(athlete, "/athlete/shoes", {
        method: "POST",
        body: JSON.stringify({ name: "Lab trainers" }),
      });
      check(shoe.is_default, "The first pair of shoes did not become the default");

      // Two real submissions, a week apart, straight north at 5:00 /km.
      const submit = async (daysAgo: number, km: number) => {
        const start = Date.now() - daysAgo * 86_400_000;
        const speed = 1000 / 300;
        const count = Math.floor((km * 1000) / speed / 2);
        const samples = Array.from({ length: count + 1 }, (_, i) => ({
          ts: start + i * 2000,
          lat: BENGALURU.lat + 0.02 + (i * 2 * speed) / 111_195,
          lon: BENGALURU.lon + 0.05,
          accuracy_m: 5,
          speed_mps: speed,
          provider: "lab",
          is_mock: false,
          altitude_m: 900 + Math.min(i, 150) * 0.1,
        }));
        const body = {
          run_id: crypto.randomUUID(),
          started_at: new Date(start).toISOString(),
          ended_at: new Date(start + count * 2000).toISOString(),
          samples,
          conditions: { temperature_c: 26, weather_code: 2 },
        };
        return asRunner<any>(athlete, "/runs", { method: "POST", body: JSON.stringify(body) });
      };
      const older = await submit(8, 5.2);
      const recent = await submit(1, 3.1);
      log("Two runs submitted a week apart");

      const stats = await asRunner<any>(athlete, "/athlete/stats?tz=UTC");
      check(stats.all_time.runs === 2, `Expected 2 runs in all-time stats, got ${stats.all_time.runs}`);
      check(stats.streak.best_weeks >= 1, "The weekly streak was not counted");
      check(
        stats.best_efforts.some((effort: any) => effort.distance_m === 5000),
        "A 5.2 km run produced no 5K best effort",
      );
      check(stats.longest_run?.run_id === older.run_id, "The longest run is not the 5.2 km one");
      log(`Stats: ${stats.all_time.runs} runs, ${(stats.all_time.distance_m / 1000).toFixed(1)} km, streak ${stats.streak.current_weeks}`);

      const goal = await asRunner<any>(athlete, "/athlete/goal?tz=UTC", {
        method: "PUT",
        body: JSON.stringify({ metric: "runs", target: 3 }),
      });
      check(goal.target === 3, "The weekly goal was not saved");
      log(`Weekly goal: ${goal.value} of ${goal.target} runs`);

      const shoes = await asRunner<any[]>(athlete, "/athlete/shoes");
      check(shoes[0].runs === 2, `The default shoes should have carried 2 runs, not ${shoes[0].runs}`);

      await asRunner(athlete, `/athlete/runs/${recent.run_id}`, {
        method: "PATCH",
        body: JSON.stringify({ title: "Lab shakeout", note: "Private note" }),
      });
      const activity = await asRunner<any>(athlete, `/athlete/runs/${recent.run_id}`);
      check(activity.summary.title === "Lab shakeout", "The run title did not save");
      check(activity.splits.length >= 3, "A 3.1 km run should have at least three splits");
      check(activity.summary.temperature_c === 26, "The run's weather was not kept");
      log(`Run detail: ${activity.splits.length} splits, ${activity.best_efforts.length} best efforts`);

      let refused = false;
      try {
        await asRunner(friend, `/social/accounts/${athlete.account_id}/profile`);
      } catch {
        refused = true;
      }
      check(refused, "A stranger could open the athlete's profile");

      await friends(athlete, friend);
      const profile = await asRunner<any>(friend, `/social/accounts/${athlete.account_id}/profile`);
      check(profile.all_time.runs === 2, "A friend sees the wrong run count");
      check(
        profile.recent_runs.every((run: any) => run.note === null && run.shoe === null),
        "A friend can see private notes or shoes",
      );
      log("Friend profile: stats visible, notes and shoes hidden");
    },
  },
];

import { useCallback, useEffect, useState } from "react";
import { api, asRunner, type TestRunner } from "../lib/api";

/**
 * Manual controls for whichever test runner is active.
 *
 * Everything here is the player API, called with that runner's session. The
 * scripted checks prove a feature works; this is for poking at it — reproducing
 * an odd state, or seeing what something looks like mid-flight.
 */

type Props = {
  active: TestRunner;
  runners: TestRunner[];
  onChanged: () => void;
};

function message(error: unknown) {
  return error instanceof Error ? error.message : "Something went wrong";
}

export default function LabActions({ active, runners, onChanged }: Props) {
  const [friends, setFriends] = useState<any>({ friends: [], incoming: [], outgoing: [] });
  const [challenges, setChallenges] = useState<any[]>([]);
  const [races, setRaces] = useState<any[]>([]);
  const [notice, setNotice] = useState("");
  const others = runners.filter((row) => row.account_id !== active.account_id);

  const load = useCallback(async () => {
    try {
      const [friendList, challengeList, raceList] = await Promise.all([
        asRunner<any>(active, "/social/friends"),
        asRunner<any[]>(active, "/social/challenges"),
        asRunner<any[]>(active, "/social/races"),
      ]);
      setFriends(friendList);
      setChallenges(challengeList);
      setRaces(raceList);
    } catch (error) {
      setNotice(message(error));
    }
  }, [active]);

  useEffect(() => {
    void load();
  }, [load]);

  const act = async (work: () => Promise<unknown>, success: string) => {
    setNotice("");
    try {
      await work();
      setNotice(success);
      await load();
      onChanged();
    } catch (error) {
      setNotice(message(error));
    }
  };

  const isFriend = (id: string) =>
    friends.friends?.some((row: any) => row.account.id === id);

  return (
    <div className="lab-actions">
      <span className="eyebrow">ACTING AS @{active.handle}</span>

      <h3>Friends</h3>
      {others.length === 0 ? (
        <p className="lab-note">Add a second runner to try anything social.</p>
      ) : (
        <ul className="lab-rows">
          {others.map((other) => (
            <li key={other.account_id}>
              <span>{other.display_name}</span>
              {isFriend(other.account_id) ? (
                <em>friends</em>
              ) : (
                <button
                  className="text-btn"
                  onClick={() =>
                    act(
                      () =>
                        asRunner(active, "/social/friends/requests", {
                          method: "POST",
                          body: JSON.stringify({ handle: other.handle }),
                        }),
                      `Request sent to ${other.display_name}`,
                    )
                  }
                >
                  Add
                </button>
              )}
            </li>
          ))}
        </ul>
      )}

      {friends.incoming?.length > 0 && (
        <>
          <h3>Requests</h3>
          <ul className="lab-rows">
            {friends.incoming.map((request: any) => (
              <li key={request.id}>
                <span>{request.account.display_name}</span>
                <button
                  className="text-btn"
                  onClick={() =>
                    act(
                      () =>
                        asRunner(active, `/social/friends/requests/${request.id}/accept`, {
                          method: "POST",
                        }),
                      "Accepted",
                    )
                  }
                >
                  Accept
                </button>
              </li>
            ))}
          </ul>
        </>
      )}

      {friends.friends?.length > 0 && (
        <>
          <h3>Sharing</h3>
          <ul className="lab-rows">
            {friends.friends.map((friend: any) => (
              <li key={friend.account.id}>
                <span>{friend.account.display_name}</span>
                <span className="lab-row-buttons">
                  <button
                    className="text-btn"
                    onClick={() =>
                      act(
                        () =>
                          asRunner(active, `/social/sharing/${friend.account.id}`, {
                            method: "PUT",
                            body: JSON.stringify({ share_location: true }),
                          }),
                        `Sharing location with ${friend.account.display_name}`,
                      )
                    }
                  >
                    Share
                  </button>
                  <button
                    className="text-btn"
                    onClick={() =>
                      act(
                        () =>
                          asRunner(active, `/social/sharing/${friend.account.id}`, {
                            method: "PUT",
                            body: JSON.stringify({ share_location: false }),
                          }),
                        "Sharing off",
                      )
                    }
                  >
                    Stop
                  </button>
                </span>
              </li>
            ))}
          </ul>

          <h3>Challenge</h3>
          <ul className="lab-rows">
            {friends.friends.map((friend: any) => (
              <li key={friend.account.id}>
                <span>{friend.account.display_name}</span>
                <button
                  className="text-btn"
                  onClick={() =>
                    act(
                      () =>
                        asRunner(active, "/social/challenges", {
                          method: "POST",
                          body: JSON.stringify({
                            opponent_id: friend.account.id,
                            metric: "distance",
                            comparison: "most",
                            window_days: 3,
                            goal_text: `More distance than ${friend.account.display_name}`,
                          }),
                        }),
                      "Challenge sent",
                    )
                  }
                >
                  Challenge
                </button>
              </li>
            ))}
          </ul>
        </>
      )}

      {challenges.length > 0 && (
        <>
          <h3>Open challenges</h3>
          <ul className="lab-rows">
            {challenges.slice(0, 5).map((challenge: any) => (
              <li key={challenge.id}>
                <span>
                  {challenge.goal_text}
                  <em> {challenge.status}</em>
                </span>
                <span className="lab-row-buttons">
                  {challenge.status === "pending" && challenge.role === "opponent" && (
                    <button
                      className="text-btn"
                      onClick={() =>
                        act(
                          () =>
                            asRunner(active, `/social/challenges/${challenge.id}/accept`, {
                              method: "POST",
                            }),
                          "Accepted",
                        )
                      }
                    >
                      Accept
                    </button>
                  )}
                  {challenge.status === "accepted" && (
                    <button
                      className="text-btn"
                      onClick={() =>
                        act(
                          () => api.fastForwardChallenge(challenge.id),
                          "Window closed and settled",
                        )
                      }
                    >
                      Settle now
                    </button>
                  )}
                </span>
              </li>
            ))}
          </ul>
        </>
      )}

      {races.filter((race) => race.status === "pending" || race.status === "running").length >
        0 && (
        <>
          <h3>Races</h3>
          <ul className="lab-rows">
            {races
              .filter((race) => race.status === "pending" || race.status === "running")
              .map((race: any) => (
                <li key={race.id}>
                  <span>
                    {race.pin_label ?? "Dropped pin"}
                    <em> {race.status}</em>
                  </span>
                  {race.status === "pending" && race.role === "opponent" && (
                    <button
                      className="text-btn"
                      onClick={() =>
                        act(
                          () =>
                            asRunner(active, `/social/races/${race.id}/accept`, {
                              method: "POST",
                            }),
                          "Race accepted",
                        )
                      }
                    >
                      Accept
                    </button>
                  )}
                </li>
              ))}
          </ul>
        </>
      )}

      <h3>Ledger</h3>
      <button
        className="text-btn"
        onClick={() =>
          act(
            () => api.addSyntheticRun(active.account_id, 5000),
            "Added a 5 km run to this runner",
          )
        }
      >
        Add a 5 km run
      </button>

      {notice && <p className="lab-note" role="status">{notice}</p>}
    </div>
  );
}

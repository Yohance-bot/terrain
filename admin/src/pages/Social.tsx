import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Users,
  Flag,
  Timer,
  Ghost,
  MapPin,
  Bell,
  ShieldAlert,
  RefreshCw,
} from "lucide-react";
import { api } from "../lib/api";

/**
 * Operational view of the social layer.
 *
 * There is no location anywhere on this page. The server never sends a
 * position to the console, and the value of `players sharing now` is a count of
 * who is reporting, not a way to find them. A player's opt-in is to their
 * friends, not to whoever holds an operator login.
 */

type Tab = "challenges" | "races" | "ghosts";

const formatKm = (metres: number | null) =>
  metres === null || metres === undefined ? "—" : `${(metres / 1000).toFixed(2)} km`;

const formatDuration = (seconds: number | null) => {
  if (seconds === null || seconds === undefined) return "—";
  const minutes = Math.floor(seconds / 60);
  return `${minutes}:${String(Math.round(seconds % 60)).padStart(2, "0")}`;
};

/** Challenge values carry different units per metric, so they format per metric. */
function formatMetric(metric: string, value: number | null) {
  if (value === null || value === undefined) return "—";
  if (metric === "distance") return formatKm(value);
  if (metric === "moving_time") return `${Math.round(value / 60)} min`;
  if (metric === "captured_area")
    return value >= 10000 ? `${(value / 10000).toFixed(2)} ha` : `${Math.round(value)} m²`;
  return String(Math.round(value));
}

export default function Social() {
  const [tab, setTab] = useState<Tab>("challenges");
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState("");
  const query = useQueryClient();

  const overview = useQuery({
    queryKey: ["social-overview"],
    queryFn: api.getSocialOverview,
    refetchInterval: 15000,
  });
  const health = useQuery({
    queryKey: ["social-health"],
    queryFn: api.getSocialHealth,
    refetchInterval: 15000,
  });
  const challenges = useQuery({
    queryKey: ["social-challenges"],
    queryFn: () => api.getSocialChallenges(50),
    refetchInterval: 20000,
    enabled: tab === "challenges",
  });
  const races = useQuery({
    queryKey: ["social-races"],
    queryFn: () => api.getSocialRaces(50),
    refetchInterval: 20000,
    enabled: tab === "races",
  });
  const ghosts = useQuery({
    queryKey: ["social-ghosts"],
    queryFn: () => api.getSocialGhosts(50),
    refetchInterval: 30000,
    enabled: tab === "ghosts",
  });

  const stats = overview.data;
  const cards = [
    ["Friendships", stats?.friendships_accepted, Users, `${stats?.friend_requests_pending ?? 0} awaiting a reply`],
    ["Sharing location", stats?.sharing_location, MapPin, `${stats?.players_visible_now ?? 0} reporting right now`],
    ["Run-start alerts", stats?.sharing_run_starts, Bell, "A separate opt-in from location"],
    ["Challenges running", stats?.challenges_open, Flag, `${stats?.challenges_resolved ?? 0} settled`],
    ["Races running", stats?.races_running, Timer, `${stats?.races_finished ?? 0} finished`],
    ["Ghosts", stats?.ghosts_total, Ghost, `${stats?.ghosts_public ?? 0} broadcast publicly`],
  ] as const;

  const overdue = health.data?.challenges_overdue ?? 0;

  async function resolveNow() {
    if (busy) return;
    setBusy(true);
    setNotice("");
    try {
      const result = await api.resolveSocial();
      setNotice(
        `Settled ${result.resolved} challenge${result.resolved === 1 ? "" : "s"} and expired ${result.expired}.`,
      );
      await query.invalidateQueries();
    } catch (error) {
      setNotice((error as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="page">
      <header className="page-title">
        <div>
          <span className="eyebrow">SOCIAL LAYER</span>
          <h1>Rivalries, not surveillance.</h1>
          <p>
            Friendships, challenges, races and ghosts. Player locations are never sent to this
            console — only whether sharing is switched on.
          </p>
        </div>
        <button className="primary-btn" disabled={busy} onClick={() => void resolveNow()}>
          <RefreshCw size={17} /> {busy ? "Settling…" : "Settle what is due"}
        </button>
      </header>

      {overview.error && <p className="error">{overview.error.message}</p>}
      {notice && <p className="system-note">{notice}</p>}

      {/* The deployment has no worker, so anything past its window and unsettled
          is real work waiting on somebody opening the app. Worth seeing. */}
      {overdue > 0 && (
        <p className="error">
          <ShieldAlert size={16} /> {overdue} challenge{overdue === 1 ? "" : "s"} finished but
          {" "}unsettled
          {health.data?.oldest_overdue_challenge_hours
            ? `, the oldest by ${health.data.oldest_overdue_challenge_hours}h`
            : ""}
          . Settle them above, or schedule the resolver.
        </p>
      )}

      <div className="metric-grid">
        {cards.map(([label, value, Icon, note]) => (
          <article className="metric" key={label}>
            <div>
              <span>{label}</span>
              <Icon size={19} />
            </div>
            <strong>{value?.toLocaleString() ?? "—"}</strong>
            <small>{note}</small>
          </article>
        ))}
      </div>

      <div className="segmented">
        {(["challenges", "races", "ghosts"] as Tab[]).map((option) => (
          <button
            key={option}
            className={tab === option ? "selected" : ""}
            onClick={() => setTab(option)}
          >
            {option[0]!.toUpperCase() + option.slice(1)}
          </button>
        ))}
      </div>

      {tab === "challenges" && (
        <div className="panel table-panel">
          <table>
            <thead>
              <tr>
                <th>Between</th>
                <th>Condition</th>
                <th>Status</th>
                <th>Standing</th>
                <th>Stake</th>
                <th>Ends</th>
              </tr>
            </thead>
            <tbody>
              {challenges.isPending ? (
                <tr>
                  <td colSpan={6}>Loading challenges…</td>
                </tr>
              ) : !challenges.data?.length ? (
                <tr>
                  <td colSpan={6}>Nobody has challenged anybody yet.</td>
                </tr>
              ) : (
                challenges.data.map((row: any) => (
                  <tr key={row.id}>
                    <td>
                      <strong>
                        {row.challenger} vs {row.opponent}
                      </strong>
                      <small>{row.goal_text}</small>
                    </td>
                    <td>
                      {row.comparison === "fastest_to" ? "First to" : "Most"} {row.metric.replace("_", " ")}
                    </td>
                    <td>
                      <span className={`badge ${row.status}`}>{row.status}</span>
                      {row.winner && <small>{row.winner} won</small>}
                    </td>
                    <td>
                      {formatMetric(row.metric, row.challenger_value)}
                      {" · "}
                      {formatMetric(row.metric, row.opponent_value)}
                    </td>
                    <td>
                      {row.staked_area_m2
                        ? `${Math.round(row.staked_area_m2)} m²${row.stake_transferred ? " (moved)" : ""}`
                        : "—"}
                    </td>
                    <td>{new Date(row.window_end).toLocaleString()}</td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      )}

      {tab === "races" && (
        <div className="panel table-panel">
          <table>
            <thead>
              <tr>
                <th>Between</th>
                <th>Destination</th>
                <th>Status</th>
                <th>Winner</th>
                <th>Started</th>
              </tr>
            </thead>
            <tbody>
              {races.isPending ? (
                <tr>
                  <td colSpan={5}>Loading races…</td>
                </tr>
              ) : !races.data?.length ? (
                <tr>
                  <td colSpan={5}>No races yet.</td>
                </tr>
              ) : (
                races.data.map((row: any) => (
                  <tr key={row.id}>
                    <td>
                      <strong>
                        {row.challenger} vs {row.opponent}
                      </strong>
                    </td>
                    <td>
                      {row.label ?? "A dropped pin"}
                      <small>within {Math.round(row.radius_m)} m</small>
                    </td>
                    <td>
                      <span className={`badge ${row.status}`}>{row.status}</span>
                    </td>
                    <td>{row.winner ?? "—"}</td>
                    <td>
                      {row.started_at ? new Date(row.started_at).toLocaleString() : "Not started"}
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
          <div className="system-note">
            <span className="status-dot" />
            Pin coordinates are not sent to the console
            <small>A race is a destination a player chose, not an operational record.</small>
          </div>
        </div>
      )}

      {tab === "ghosts" && (
        <div className="panel table-panel">
          <table>
            <thead>
              <tr>
                <th>Ghost</th>
                <th>Owner</th>
                <th>Route</th>
                <th>Visibility</th>
                <th>Attempts</th>
                <th>Best</th>
              </tr>
            </thead>
            <tbody>
              {ghosts.isPending ? (
                <tr>
                  <td colSpan={6}>Loading ghosts…</td>
                </tr>
              ) : !ghosts.data?.length ? (
                <tr>
                  <td colSpan={6}>No ghosts recorded yet.</td>
                </tr>
              ) : (
                ghosts.data.map((row: any) => (
                  <tr key={row.id}>
                    <td>
                      <strong>{row.name}</strong>
                      <small>{new Date(row.created_at).toLocaleDateString()}</small>
                    </td>
                    <td>{row.owner}</td>
                    <td>
                      {formatKm(row.distance_m)}
                      <small>{formatDuration(row.duration_s)}</small>
                    </td>
                    <td>
                      <span className={`badge ${row.is_public ? "applied" : "submitted"}`}>
                        {row.is_public ? "broadcast" : "private"}
                      </span>
                      {row.share_live_location && <small>also shares live position</small>}
                    </td>
                    <td>{row.attempts}</td>
                    <td>{formatDuration(row.best_elapsed_s)}</td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
          <div className="system-note">
            <span className="status-dot" />
            Recorded routes stay with their runner
            <small>
              The console sees a ghost's shape and use, never the path it follows.
            </small>
          </div>
        </div>
      )}
    </div>
  );
}

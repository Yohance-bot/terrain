import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { ArrowUpRight, Activity, MapPin, Users, Flag } from "lucide-react";
import { api } from "../lib/api";
import WorldMap from "../components/WorldMap";
import { useWorldData } from "../features/useWorldData";
export default function Dashboard() {
  const stats = useQuery({
      queryKey: ["stats"],
      queryFn: api.getStats,
      refetchInterval: 15000,
    }),
    runs = useQuery({
      queryKey: ["recent-runs"],
      queryFn: () => api.getRuns(0, 6),
      refetchInterval: 15000,
    }),
    world = useWorldData();
  const cards = [
    ["Territories", stats.data?.total_territories, MapPin],
    ["Runners", stats.data?.total_accounts, Users],
    ["Recorded runs", stats.data?.total_runs, Activity],
    ["Active leaders", stats.data?.active_owners, Flag],
  ] as const;
  return (
    <div className="page overview">
      <header className="page-title">
        <div>
          <span className="eyebrow">CITY OPERATIONS / BENGALURU</span>
          <h1>A world in motion.</h1>
          <p>Your runners, streets and territory. One shared world.</p>
        </div>
        <Link className="primary-btn" to="/simulation">
          Launch simulator <ArrowUpRight size={18} />
        </Link>
      </header>
      {stats.error && <p className="error">{stats.error.message}</p>}
      <div className="metric-grid">
        {cards.map(([label, value, Icon]) => (
          <article className="metric" key={label}>
            <div>
              <span>{label}</span>
              <Icon size={19} />
            </div>
            <strong>{value?.toLocaleString() ?? "—"}</strong>
            <small>Live server total</small>
          </article>
        ))}
      </div>
      <div className="overview-grid">
        <section className="world-preview">
          <WorldMap territories={world.territories} captures={world.captures} />
          <div className="preview-caption glass">
            <span className="eyebrow">YOUR WORLD</span>
            <h2>Bengaluru, from above.</h2>
            <Link to="/map">
              Explore the map <ArrowUpRight size={17} />
            </Link>
          </div>
        </section>
        <section className="panel recent-panel">
          <div className="section-title">
            <h2>Latest activity</h2>
            <Link to="/runs">View all ↗</Link>
          </div>
          {runs.isPending ? (
            <p>Loading activity…</p>
          ) : runs.error ? (
            <p className="error">{runs.error.message}</p>
          ) : !runs.data?.items.length ? (
            <p>No runs recorded yet.</p>
          ) : (
            runs.data.items.map((r: any) => (
              <Link
                to={`/runs?run=${r.run_id}`}
                key={r.run_id}
                className="activity-row"
              >
                <div className="activity-icon">
                  <Activity size={18} />
                </div>
                <div>
                  <strong>{r.display_name ?? "Unlinked runner"}</strong>
                  <small>{new Date(r.started_at).toLocaleString()}</small>
                </div>
                <span>
                  <b>{(r.distance_m / 1000).toFixed(2)} km</b>
                  <small>{r.status}</small>
                </span>
              </Link>
            ))
          )}
          <div className="system-note">
            <span className="status-dot" />
            Synced with the app
            <small>
              Both clients use the same Render API and Supabase database.
            </small>
          </div>
        </section>
      </div>
      <div className="overview-footer">
        <span>◈ TerraRun Operations</span>
        <span>
          Updated{" "}
          {stats.dataUpdatedAt
            ? new Date(stats.dataUpdatedAt).toLocaleTimeString()
            : "—"}
        </span>
      </div>
    </div>
  );
}

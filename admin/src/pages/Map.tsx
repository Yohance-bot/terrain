import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { Gamepad2, Moon, Sun, X } from "lucide-react";
import WorldMap from "../components/WorldMap";
import { useWorldData } from "../features/useWorldData";
import { api } from "../lib/api";
export default function TerritoryMap() {
  const world = useWorldData(),
    query = useQueryClient();
  const [night, setNight] = useState(false),
    [selected, setSelected] = useState<GeoJSON.Feature | null>(null),
    [notice, setNotice] = useState("");
  const id = String(selected?.properties?.territory_id ?? "");
  const details = useQuery({
    queryKey: ["territory", id],
    queryFn: () => api.getTerritoryDetails(id),
    enabled: !!id,
    refetchInterval: 15000,
  });
  async function rebuild() {
    const reason = window.prompt(
      "Reason for rebuilding this territory from its run ledger:",
    );
    if (!reason?.trim()) return;
    setNotice("Rebuilding…");
    try {
      await api.rebuildTerritory(id, "admin-console", reason.trim());
      await query.invalidateQueries();
      setNotice("Standings rebuilt from authoritative runs.");
    } catch (e) {
      setNotice((e as Error).message);
    }
  }
  return (
    <div className="map-page">
      <WorldMap
        territories={world.territories}
        captures={world.captures}
        night={night}
        onSelect={setSelected}
      />
      <div className="map-heading glass">
        <span className="eyebrow">LIVE WORLD</span>
        <h1>Bengaluru</h1>
        <p>
          {world.loading
            ? "Loading the city…"
            : `${world.territories?.features.length ?? 0} territories · synced ${world.updatedAt ? new Date(world.updatedAt).toLocaleTimeString() : "—"}`}
        </p>
        {world.error && <p className="error">{world.error.message}</p>}
      </div>
      <div className="map-actions">
        <button onClick={() => setNight(!night)}>
          {night ? <Sun size={18} /> : <Moon size={18} />}{" "}
          {night ? "Day" : "Night"}
        </button>
        <Link to="/simulation">
          <Gamepad2 size={18} />
          Simulate a run
        </Link>
      </div>
      <div className="map-legend glass">
        <span>
          <i style={{ background: "#22C55E" }} />
          Developer 1
        </span>
        <span>
          <i style={{ background: "#A855F7" }} />
          Developer 2
        </span>
        <span>
          <i style={{ background: "#F97316" }} />
          Developer 3
        </span>
        <span>
          <i style={{ background: "#6B9584" }} />
          Unclaimed
        </span>
      </div>
      {selected && (
        <aside className="inspector glass">
          <button
            className="close"
            onClick={() => setSelected(null)}
            aria-label="Close territory"
          >
            <X size={18} />
          </button>
          <span className="eyebrow">TERRITORY INSPECTOR</span>
          <h2>{selected.properties?.name}</h2>
          <p className="mono">{id}</p>
          {details.isPending ? (
            <p>Loading standings…</p>
          ) : details.error ? (
            <p className="error">{details.error.message}</p>
          ) : (
            <>
              <label>Current leader</label>
              <p className="mono">
                {details.data?.owner_device_id ?? "Unclaimed"}
              </p>
              <label>Standings</label>
              {(details.data?.standings ?? []).length === 0 && (
                <p className="lab-note">
                  No runs recorded here yet. Most of the city is still untouched —
                  the Standings page lists the territories that are live.
                </p>
              )}
              <div className="standing-list">
                {(details.data?.standings ?? []).map((s: any) => (
                  <div key={s.device_id}>
                    <strong>{s.display_name ?? s.device_id.slice(0, 8)}</strong>
                    <span>
                      {Number(s.total_distance_m ?? s.distance_m ?? 0).toFixed(
                        0,
                      )}{" "}
                      m
                    </span>
                  </div>
                ))}
              </div>
            </>
          )}
          <button className="secondary-btn" onClick={() => void rebuild()}>
            Rebuild standings
          </button>
          {notice && <p role="status">{notice}</p>}
        </aside>
      )}
    </div>
  );
}

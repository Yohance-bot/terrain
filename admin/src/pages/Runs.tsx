import { useState } from "react";
import { useSearchParams } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { X } from "lucide-react";
import { api } from "../lib/api";
import WorldMap from "../components/WorldMap";
export default function Runs() {
  const [page, setPage] = useState(0),
    [params, setParams] = useSearchParams(),
    [reason, setReason] = useState(""),
    [busy, setBusy] = useState(false),
    [notice, setNotice] = useState("");
  const id = params.get("run") ?? "",
    query = useQueryClient();
  const runs = useQuery({
      queryKey: ["runs", page],
      queryFn: () => api.getRuns(page * 50, 50),
      refetchInterval: 15000,
    }),
    detail = useQuery({
      queryKey: ["run", id],
      queryFn: () => api.getRunDetails(id),
      enabled: !!id,
    });
  async function reverse() {
    if (!reason.trim() || busy) return;
    setBusy(true);
    setNotice("");
    try {
      await api.reverseRun(id, "admin-console", reason.trim());
      await query.invalidateQueries();
      setNotice("Run reversed. Its evidence remains in the audit trail.");
      setReason("");
    } catch (e) {
      setNotice((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  const route: GeoJSON.FeatureCollection<GeoJSON.LineString> = {
    type: "FeatureCollection",
    features:
      detail.data?.geometry?.type === "LineString"
        ? [{ type: "Feature", properties: {}, geometry: detail.data.geometry }]
        : [],
  };
  return (
    <div className="page">
      <header className="page-title">
        <div>
          <span className="eyebrow">RUN LEDGER</span>
          <h1>Every run has a story.</h1>
          <p>Inspect routes, verify outcomes and reverse invalid activity.</p>
        </div>
        <span className="count-chip">{runs.data?.total ?? "—"} runs</span>
      </header>
      {runs.error && <p className="error">{runs.error.message}</p>}
      <div className="panel table-panel">
        <table>
          <thead>
            <tr>
              <th>Runner</th>
              <th>Status</th>
              <th>Distance</th>
              <th>Started</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {runs.isPending ? (
              <tr>
                <td colSpan={5}>Loading runs…</td>
              </tr>
            ) : !runs.data?.items.length ? (
              <tr>
                <td colSpan={5}>No runs yet.</td>
              </tr>
            ) : (
              runs.data.items.map((run: any) => (
                <tr key={run.run_id}>
                  <td>
                    <strong>{run.display_name ?? "Unlinked runner"}</strong>
                    <small className="mono">{run.run_id}</small>
                  </td>
                  <td>
                    <span className={`badge ${run.status}`}>{run.status}</span>
                  </td>
                  <td>{(run.distance_m / 1000).toFixed(2)} km</td>
                  <td>{new Date(run.started_at).toLocaleString()}</td>
                  <td>
                    <button
                      className="text-btn"
                      onClick={() => {
                        setParams({ run: run.run_id });
                        setNotice("");
                      }}
                    >
                      Inspect ↗
                    </button>
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
        <div className="pagination">
          <span>
            {runs.data?.total
              ? `${page * 50 + 1}–${Math.min((page + 1) * 50, runs.data.total)} of ${runs.data.total}`
              : "0 runs"}
          </span>
          <button disabled={!page} onClick={() => setPage(page - 1)}>
            Previous
          </button>
          <button
            disabled={(page + 1) * 50 >= (runs.data?.total ?? 0)}
            onClick={() => setPage(page + 1)}
          >
            Next
          </button>
        </div>
      </div>
      {id && (
        <div className="drawer-backdrop">
          <section className="run-drawer">
            <button
              className="close"
              onClick={() => setParams({})}
              aria-label="Close run"
            >
              <X />
            </button>
            <span className="eyebrow">ACTIVITY INSPECTOR</span>
            <h2>
              {detail.data?.simulation ? "Developer simulation" : "Run detail"}
            </h2>
            <p className="mono">{id}</p>
            {detail.isPending ? (
              <p>Loading run…</p>
            ) : detail.error ? (
              <p className="error">{detail.error.message}</p>
            ) : (
              <>
                <div className="run-map">
                  <WorldMap
                    route={route}
                    position={
                      route.features[0]?.geometry.coordinates[0] as
                        [number, number] | undefined
                    }
                  />
                </div>
                <div className="run-facts">
                  <span>
                    <b>{detail.data.result.distance_m.toFixed(0)} m</b>Distance
                  </span>
                  <span>
                    <b>{detail.data.result.duration_s}s</b>Duration
                  </span>
                  <span>
                    <b>{detail.data.result.status}</b>Status
                  </span>
                </div>
                {detail.data.route_reduced && (
                  <p>
                    Route precision has been reduced by the retention policy.
                  </p>
                )}
                <h3>Territory contributions</h3>
                {detail.data.result.segments.map((s: any) => (
                  <div className="activity-row" key={s.territory_id}>
                    <strong>{s.name}</strong>
                    <span>
                      {s.distance_m.toFixed(0)} m
                      {s.capture_method ? " · Loop claim" : ""}
                    </span>
                  </div>
                ))}
                {["applied", "provisional", "challenged"].includes(
                  detail.data.result.status,
                ) && (
                  <div className="reversal">
                    <h3>Reverse this run</h3>
                    <p>
                      Removes its influence and rebuilds standings. The run and
                      its evidence remain recorded.
                    </p>
                    <label>
                      Audit reason
                      <textarea
                        value={reason}
                        onChange={(e) => setReason(e.target.value)}
                        maxLength={512}
                      />
                    </label>
                    <button
                      className="danger-btn"
                      disabled={busy || !reason.trim()}
                      onClick={() => void reverse()}
                    >
                      {busy ? "Reversing…" : "Confirm reversal"}
                    </button>
                  </div>
                )}
                {notice && <p role="status">{notice}</p>}
              </>
            )}
          </section>
        </div>
      )}
    </div>
  );
}

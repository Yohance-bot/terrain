import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../lib/api";

/**
 * Who holds what.
 *
 * Most of a city has never been run through, so the default view is the
 * territories that actually have someone standing in them — the problem was
 * never that standings were missing, it was having to guess which of several
 * hundred territories had any.
 */

function km(metres: number) {
  return metres >= 1000 ? `${(metres / 1000).toFixed(2)} km` : `${Math.round(metres)} m`;
}

export default function Standings() {
  const [all, setAll] = useState(false);
  const [selected, setSelected] = useState<string | null>(null);
  const [notice, setNotice] = useState("");
  const query = useQueryClient();

  const standings = useQuery({
    queryKey: ["standings", all],
    queryFn: () => api.getStandings(!all),
    refetchInterval: 20000,
  });
  const detail = useQuery({
    queryKey: ["territory", selected],
    queryFn: () => api.getTerritoryDetails(selected!),
    enabled: !!selected,
  });
  const assignable = useQuery({
    queryKey: ["assignable"],
    queryFn: api.getAssignable,
    enabled: !!selected,
  });

  async function assign(accountId: string | null) {
    if (!selected) return;
    const reason = window.prompt(
      accountId ? "Why are you assigning this territory?" : "Why are you clearing it?",
    );
    if (!reason?.trim()) return;
    setNotice("Writing to the ledger…");
    try {
      await api.assignTerritory(selected, accountId, reason.trim());
      await query.invalidateQueries();
      setNotice(
        accountId
          ? "Assigned. The grant is in the influence ledger, so it survives the next run."
          : "Cleared. This territory is unclaimed again.",
      );
    } catch (error) {
      setNotice((error as Error).message);
    }
  }

  const items = standings.data?.items ?? [];

  return (
    <div className="page">
      <header className="page-title">
        <div>
          <span className="eyebrow">TERRITORY STANDINGS</span>
          <h1>Who holds the ground.</h1>
          <p>
            {standings.data
              ? `${standings.data.contested} of ${standings.data.total} territories have been run through.`
              : "Reading the ledger…"}
          </p>
        </div>
        <button className="secondary-btn" onClick={() => setAll(!all)}>
          {all ? "Only contested" : "Show every territory"}
        </button>
      </header>

      {standings.error && <p className="error">{standings.error.message}</p>}
      {notice && <p className="system-note">{notice}</p>}

      <div className="standings-layout">
        <ul className="standings-list">
          {standings.isPending ? (
            <li className="standings-empty">Loading…</li>
          ) : items.length === 0 ? (
            <li className="standings-empty">
              Nobody has run anywhere yet. Drive a run in the test lab to put
              something here.
            </li>
          ) : (
            items.map((row: any) => (
              <li
                key={row.territory_id}
                className={selected === row.territory_id ? "selected" : ""}
              >
                <button onClick={() => setSelected(row.territory_id)}>
                  <span className="standings-name">
                    <strong>{row.name}</strong>
                    <small>{row.owner_name ?? "Unclaimed"}</small>
                  </span>
                  <span className="standings-figures">
                    <b>{km(row.leader_distance_m)}</b>
                    <small>
                      {row.contenders} {row.contenders === 1 ? "runner" : "runners"}
                    </small>
                  </span>
                </button>
              </li>
            ))
          )}
        </ul>

        <aside className="standings-detail panel">
          {!selected ? (
            <p className="lab-note">Pick a territory to see who is standing in it.</p>
          ) : detail.isPending ? (
            <p>Loading standings…</p>
          ) : detail.error ? (
            <p className="error">{detail.error.message}</p>
          ) : (
            <>
              <span className="eyebrow">{detail.data?.kind?.toUpperCase()}</span>
              <h2>{detail.data?.name}</h2>
              {(detail.data?.standings ?? []).length === 0 ? (
                <p className="lab-note">
                  No runs have been recorded here yet, so there is nothing to rank.
                </p>
              ) : (
                <ol className="standings-rank">
                  {detail.data.standings.map((entry: any) => (
                    <li key={entry.device_id} className={entry.is_owner ? "owner" : ""}>
                      <span>{entry.display_name}</span>
                      <span className="standings-figures">
                        <b>{km(entry.total_distance_m)}</b>
                        <small>{entry.share}%</small>
                      </span>
                    </li>
                  ))}
                </ol>
              )}

              <h3>Operator control</h3>
              <p className="lab-note">
                Ownership is derived from the influence ledger, so an assignment
                is written there rather than onto the owner row — otherwise the
                next run through would undo it.
              </p>
              <div className="standings-assign">
                <select
                  defaultValue=""
                  onChange={(e) => {
                    if (e.target.value) void assign(e.target.value);
                    e.target.value = "";
                  }}
                >
                  <option value="">Hand this territory to…</option>
                  {(assignable.data ?? []).map((account: any) => (
                    <option key={account.account_id} value={account.account_id}>
                      {account.display_name}
                      {account.is_test_runner ? " · test" : ""}
                    </option>
                  ))}
                </select>
                <button className="text-btn" onClick={() => void assign(null)}>
                  Clear it
                </button>
              </div>
            </>
          )}
        </aside>
      </div>
    </div>
  );
}

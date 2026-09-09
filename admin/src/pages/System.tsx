import { useQuery } from "@tanstack/react-query";
import { api, API_BASE_URL } from "../lib/api";
export default function System() {
  const system = useQuery({
    queryKey: ["system"],
    queryFn: api.getSystem,
    refetchInterval: 30000,
  });
  return (
    <div className="page">
      <header className="page-title">
        <div>
          <span className="eyebrow">INFRASTRUCTURE & RULES</span>
          <h1>System health.</h1>
          <p>The effective settings used by the live backend.</p>
        </div>
        <button className="secondary-btn" onClick={() => void system.refetch()}>
          Check now
        </button>
      </header>
      <div className="system-grid">
        <section className="panel">
          <span className="eyebrow">CONNECTION</span>
          <h2>
            {system.isPending
              ? "Connecting…"
              : system.error
                ? "Needs attention"
                : "Cloud connected"}
          </h2>
          {system.error && <p className="error">{system.error.message}</p>}
          <dl>
            <dt>API</dt>
            <dd className="mono">{API_BASE_URL}</dd>
            <dt>Database</dt>
            <dd>{system.data?.database ?? "—"}</dd>
            <dt>App & admin</dt>
            <dd>Same backend and source of truth</dd>
            <dt>Free instance</dt>
            <dd>May take a minute to wake after inactivity</dd>
          </dl>
          <a
            className="secondary-btn"
            href="https://dashboard.render.com/web/srv-dacll0afngtc73du0330"
            target="_blank"
            rel="noreferrer"
          >
            Open Render deployment ↗
          </a>
          <a
            className="secondary-btn"
            href="https://supabase.com/dashboard/project/wqhwnfnesigiytyhikuj"
            target="_blank"
            rel="noreferrer"
          >
            Open Supabase ↗
          </a>
        </section>
        <section className="panel">
          <span className="eyebrow">SERVER RULES</span>
          <h2>Gameplay configuration</h2>
          <p>
            These are deployment-managed values. Change them in Render and
            redeploy; this view reports what is actually running.
          </p>
          <dl>
            {Object.entries(system.data?.configuration ?? {}).map(
              ([key, value]) => (
                <div key={key}>
                  <dt>{key.replaceAll("_", " ")}</dt>
                  <dd>{String(value)}</dd>
                </div>
              ),
            )}
          </dl>
        </section>
      </div>
    </div>
  );
}

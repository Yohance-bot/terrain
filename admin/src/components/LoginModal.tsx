import { useState, type FormEvent } from "react";
import { ArrowUpRight, ShieldCheck } from "lucide-react";
import { api, setToken, API_BASE_URL } from "../lib/api";

export default function LoginModal({
  onLogin,
}: {
  onLogin: (token: string) => void;
}) {
  const [input, setInput] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!input.trim() || busy) return;
    setBusy(true);
    setError("");
    try {
      const result = await api.login(input.trim(), password);
      setToken(result.token);
      onLogin(result.token);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Unable to connect");
    } finally {
      setBusy(false);
    }
  }
  return (
    <div className="login-world">
      <div className="login-copy">
        <div className="wordmark">
          ◈ TERRARUN <span>CONTROL</span>
        </div>
        <h1>
          The city is
          <br />
          your playing field.
        </h1>
        <p>
          One view of every territory, runner and claim.
          <br />
          Connected to your live TerraRun world.
        </p>
        <span className="eyebrow">BENGALURU · OPERATIONS CONSOLE</span>
      </div>
      <form className="login-card" onSubmit={submit}>
        <ShieldCheck size={28} />
        <h2>Welcome to control.</h2>
        <p>Your own account. One shared world.</p>
        <label htmlFor="admin-token">Username</label>
        <input
          id="admin-token"
          autoComplete="username"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder="unknown.owl"
          autoFocus
          required
        />
        <label htmlFor="password">Password</label>
        <input
          id="password"
          type="password"
          autoComplete="current-password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          required
        />
        <button className="primary-btn" disabled={busy}>
          {busy ? "Connecting to Render…" : "Enter console"}
          <ArrowUpRight size={18} />
        </button>
        {error && (
          <p className="error" role="alert">
            {error}
          </p>
        )}
        <small>Session access · cleared when this tab closes</small>
        <small className="api-host">{new URL(API_BASE_URL).hostname}</small>
      </form>
    </div>
  );
}

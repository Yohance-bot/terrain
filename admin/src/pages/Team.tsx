import { useState, type FormEvent } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../lib/api";
export default function Team() {
  const me = useQuery({ queryKey: ["me"], queryFn: api.me });
  const members = useQuery({ queryKey: ["members"], queryFn: api.members });
  const cache = useQueryClient();
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  async function submit(event: FormEvent<HTMLFormElement>, create: boolean) {
    event.preventDefault();
    setBusy(true);
    setMessage("");
    const form = event.currentTarget;
    const values = Object.fromEntries(new FormData(form));
    try {
      if (create) await api.addMember(values);
      else {
        if (!values.new_password) delete values.new_password;
        await api.updateCredentials(values);
      }
      form.reset();
      await cache.invalidateQueries();
      setMessage(
        create
          ? "Account created. Share its password privately."
          : "Profile updated.",
      );
    } catch (e) {
      setMessage((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <div className="page">
      <header className="page-title">
        <div>
          <span className="eyebrow">YOUR CREW</span>
          <h1>Small team. Big world.</h1>
          <p>
            Signed in as {me.data?.display_name ?? "…"} · {me.data?.role ?? "…"}
          </p>
        </div>
      </header>
      {message && (
        <p className="panel" role="status">
          {message}
        </p>
      )}
      {me.error && <p className="error">{me.error.message}</p>}
      <div className="system-grid">
        <form
          className="panel form-stack"
          onSubmit={(e) => void submit(e, false)}
          key={me.data?.username}
        >
          <h2>Your profile</h2>
          <label>
            Display name
            <input
              name="display_name"
              defaultValue={me.data?.display_name}
              minLength={2}
              maxLength={32}
              required
            />
          </label>
          <label>
            Username
            <input
              name="username"
              defaultValue={me.data?.username}
              autoComplete="username"
              minLength={3}
              maxLength={32}
              required
            />
          </label>
          <label>
            Current password
            <input
              type="password"
              name="current_password"
              autoComplete="current-password"
              required
            />
          </label>
          <label>
            New password <small>(optional, 12+ characters)</small>
            <input
              type="password"
              name="new_password"
              autoComplete="new-password"
              minLength={12}
              maxLength={128}
            />
          </label>
          <button className="primary-btn" disabled={busy}>
            Save profile
          </button>
        </form>
        <section className="panel">
          <h2>Console access</h2>
          {members.error && <p className="error">{members.error.message}</p>}
          {members.data?.map((member: any) => (
            <div className="member-row" key={member.id}>
              <div>
                <strong>{member.display_name}</strong>
                <small>
                  @{member.username} · {member.role} ·{" "}
                  {member.active ? "Active" : "Disabled"}
                </small>
              </div>
              {me.data?.role === "owner" && member.id !== me.data.id && (
                <button
                  className="secondary-btn"
                  disabled={busy}
                  onClick={() => {
                    setBusy(true);
                    void api
                      .memberState(member.id, !member.active)
                      .then(() =>
                        cache.invalidateQueries({ queryKey: ["members"] }),
                      )
                      .catch((e) => setMessage(e.message))
                      .finally(() => setBusy(false));
                  }}
                >
                  {member.active ? "Disable" : "Enable"}
                </button>
              )}
            </div>
          ))}
        </section>
        {me.data?.role === "owner" && (
          <form
            className="panel form-stack"
            onSubmit={(e) => void submit(e, true)}
          >
            <h2>Invite another explorer</h2>
            <p>
              Create their account, then share the temporary password privately.
            </p>
            <label>
              Display name
              <input
                name="display_name"
                minLength={2}
                maxLength={32}
                required
              />
            </label>
            <label>
              Username
              <input
                name="username"
                autoComplete="off"
                pattern="[a-z0-9_.\-]{3,32}"
                required
              />
            </label>
            <label>
              Temporary password
              <input
                type="password"
                name="password"
                autoComplete="new-password"
                minLength={12}
                maxLength={128}
                required
              />
            </label>
            <label>
              Access
              <select name="role">
                <option value="admin">
                  Admin · map, runs, notes and simulation
                </option>
                <option value="owner">Owner · also manage team access</option>
              </select>
            </label>
            <button className="primary-btn" disabled={busy}>
              Create console account
            </button>
          </form>
        )}
      </div>
    </div>
  );
}

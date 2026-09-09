import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { NotebookPen, Plus, Check, Pencil } from "lucide-react";
import { api } from "../lib/api";
interface Note {
  id: string;
  title: string;
  body: string;
  status: "open" | "done";
  author: string;
  updated_at: string;
}
export default function Notes() {
  const query = useQuery({
    queryKey: ["notes"],
    queryFn: api.notes,
    refetchInterval: 15000,
  });
  const cache = useQueryClient();
  const [editing, setEditing] = useState<Note | null>(null);
  const [title, setTitle] = useState("");
  const [body, setBody] = useState("");
  const [status, setStatus] = useState("open");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  function edit(note: Note | null) {
    setEditing(note);
    setTitle(note?.title ?? "");
    setBody(note?.body ?? "");
    setStatus(note?.status ?? "open");
    setError("");
  }
  async function save() {
    setBusy(true);
    setError("");
    try {
      const value = { title, body, status };
      if (editing)
        await api.editNote(editing.id, {
          ...value,
          version: editing.updated_at,
        });
      else await api.addNote(value);
      edit(null);
      await cache.invalidateQueries({ queryKey: ["notes"] });
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <div className="page">
      <header className="page-title">
        <div>
          <span className="eyebrow">A SHARED FIELD JOURNAL</span>
          <h1>Good ideas live here.</h1>
          <p>Notes, bugs and next moves — from everyone on your team.</p>
        </div>
        <NotebookPen size={32} />
      </header>
      <div className="notes-layout">
        <section className="panel note-editor">
          <span className="eyebrow">
            {editing ? "EDIT NOTE" : "CAPTURE A THOUGHT"}
          </span>
          <input
            aria-label="Note title"
            placeholder="Give this thought a title…"
            value={title}
            maxLength={120}
            onChange={(e) => setTitle(e.target.value)}
          />
          <textarea
            aria-label="Note text"
            rows={10}
            placeholder="What did you notice? What should we build next?"
            value={body}
            maxLength={12000}
            onChange={(e) => setBody(e.target.value)}
          />
          <label>
            Status
            <select value={status} onChange={(e) => setStatus(e.target.value)}>
              <option value="open">Open</option>
              <option value="done">Done</option>
            </select>
          </label>
          {error && (
            <p className="error" role="alert">
              {error}
            </p>
          )}
          <button
            className="primary-btn"
            disabled={busy || !title.trim()}
            onClick={() => void save()}
          >
            <Plus size={16} />
            {busy ? "Saving…" : editing ? "Save changes" : "Add shared note"}
          </button>
          {editing && (
            <button className="secondary-btn" onClick={() => edit(null)}>
              Cancel edit
            </button>
          )}
        </section>
        <section className="note-list">
          {query.error && <p className="error">{query.error.message}</p>}
          {query.isPending && <p>Loading notes…</p>}
          {query.data?.length === 0 && (
            <div className="panel">
              <h2>A fresh page.</h2>
              <p>Add the first idea, observation or bug report.</p>
            </div>
          )}
          {query.data?.map((note: Note) => (
            <article className={`panel note-card ${note.status}`} key={note.id}>
              <div className="note-meta">
                <span>{note.author}</span>
                <small>{new Date(note.updated_at).toLocaleString()}</small>
              </div>
              <h2>
                {note.status === "done" && <Check size={18} />} {note.title}
              </h2>
              <p className="preserve-lines">{note.body}</p>
              <button className="secondary-btn" onClick={() => edit(note)}>
                <Pencil size={14} />
                Edit note
              </button>
            </article>
          ))}
        </section>
      </div>
    </div>
  );
}

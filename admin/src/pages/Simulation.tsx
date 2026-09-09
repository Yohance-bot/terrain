import { useEffect, useRef, useState, type PointerEvent } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { Play, Pause, RotateCcw, Navigation, Upload } from "lucide-react";
import WorldMap from "../components/WorldMap";
import { CENTER } from "../features/world";
import { useWorldData } from "../features/useWorldData";
import { api } from "../lib/api";

type Sample = {
  ts: number;
  lat: number;
  lon: number;
  accuracy_m: number;
  speed_mps: number;
  provider: string;
  is_mock: boolean;
};
type Draft = {
  slot: number;
  run_id: string;
  started_at: string;
  ended_at: string;
  samples: Sample[];
  source: "tracked";
};
const KEY = "terrarun-admin-simulation-v1";
function restore(): Draft | null {
  try {
    return JSON.parse(localStorage.getItem(KEY) || "null");
  } catch {
    return null;
  }
}
export default function Simulation() {
  const world = useWorldData(),
    query = useQueryClient();
  const [draft, setDraft] = useState<Draft | null>(restore),
    [running, setRunning] = useState(false),
    [speed, setSpeed] = useState(3),
    [rate, setRate] = useState(1),
    [slot, setSlot] = useState(() => restore()?.slot ?? 1),
    [street, setStreet] = useState(false),
    [follow, setFollow] = useState(true),
    [busy, setBusy] = useState(false),
    [result, setResult] = useState<any>(null),
    [error, setError] = useState(""),
    [reason, setReason] = useState(""),
    [operator, setOperator] = useState("admin-console");
  const [position, setPosition] = useState<[number, number]>(() => {
      const last = restore()?.samples.at(-1);
      return last ? [last.lon, last.lat] : CENTER;
    }),
    [knob, setKnob] = useState<[number, number]>([0, 0]);
  const sampleCount = useRef(draft?.samples.length ?? 0);
  useEffect(() => {
    sampleCount.current = draft?.samples.length ?? 0;
  }, [draft]);
  const direction = useRef<[number, number]>([0, 0]),
    pos = useRef(position),
    speedRef = useRef(speed),
    rateRef = useRef(rate);
  useEffect(() => {
    speedRef.current = speed;
    rateRef.current = rate;
  }, [speed, rate]);
  useEffect(() => {
    if (draft) localStorage.setItem(KEY, JSON.stringify(draft));
    else localStorage.removeItem(KEY);
  }, [draft]);
  useEffect(() => {
    if (!running) return;
    let previous = performance.now(),
      accumulator = 0;
    const tick = setInterval(() => {
      if (sampleCount.current >= 3600) {
        setRunning(false);
        return;
      }
      const now = performance.now(),
        dt = Math.min((now - previous) / 1000, 0.25) * rateRef.current;
      previous = now;
      const [x, y] = direction.current;
      pos.current = [
        pos.current[0] +
          (x * speedRef.current * dt) /
            (111320 * Math.cos((pos.current[1] * Math.PI) / 180)),
        pos.current[1] - (y * speedRef.current * dt) / 111320,
      ];
      setPosition([...pos.current]);
      accumulator += dt;
      if (accumulator >= 1) {
        const seconds = Math.floor(accumulator);
        accumulator -= seconds;
        setDraft((old) => {
          if (!old) return old;
          const last = old.samples.at(-1)!;
          const ts = last.ts + seconds * 1000;
          return {
            ...old,
            ended_at: new Date(ts).toISOString(),
            samples: [
              ...old.samples,
              {
                ts,
                lat: pos.current[1],
                lon: pos.current[0],
                accuracy_m: 5,
                speed_mps: speedRef.current * Math.hypot(x, y),
                provider: "admin-joystick",
                is_mock: false,
              },
            ].slice(0, 3600),
          };
        });
      }
    }, 100);
    return () => clearInterval(tick);
  }, [running]);

  useEffect(() => {
    function stop() {
      direction.current = [0, 0];
      setKnob([0, 0]);
      if (document.hidden) setRunning(false);
    }
    function key(e: KeyboardEvent) {
      if ((e.target as HTMLElement).matches("input,textarea,select")) return;
      const keys: Record<string, [number, number]> = {
        ArrowUp: [0, -1],
        w: [0, -1],
        ArrowDown: [0, 1],
        s: [0, 1],
        ArrowLeft: [-1, 0],
        a: [-1, 0],
        ArrowRight: [1, 0],
        d: [1, 0],
      };
      if (keys[e.key]) {
        e.preventDefault();
        direction.current = e.type === "keyup" ? [0, 0] : keys[e.key]!;
        setKnob(direction.current.map((n) => n * 34) as [number, number]);
      }
    }
    window.addEventListener("keydown", key);
    window.addEventListener("keyup", key);
    window.addEventListener("blur", stop);
    document.addEventListener("visibilitychange", stop);
    return () => {
      window.removeEventListener("keydown", key);
      window.removeEventListener("keyup", key);
      window.removeEventListener("blur", stop);
      document.removeEventListener("visibilitychange", stop);
    };
  }, []);
  function joystick(e: PointerEvent<HTMLDivElement>) {
    const r = e.currentTarget.getBoundingClientRect(),
      x = e.clientX - r.left - r.width / 2,
      y = e.clientY - r.top - r.height / 2,
      len = Math.hypot(x, y),
      scale = Math.min(1, 38 / (len || 1));
    setKnob([x * scale, y * scale]);
    direction.current = len < 7 ? [0, 0] : [x / (len || 1), y / (len || 1)];
  }
  function start() {
    if (!draft) {
      const ts = Date.now();
      setDraft({
        slot,
        run_id: crypto.randomUUID(),
        started_at: new Date(ts).toISOString(),
        ended_at: new Date(ts).toISOString(),
        source: "tracked",
        samples: [
          {
            ts,
            lat: position[1],
            lon: position[0],
            accuracy_m: 5,
            speed_mps: 0,
            provider: "admin-joystick",
            is_mock: false,
          },
        ],
      });
    }
    setRunning(!running);
  }
  function reset() {
    if (
      draft &&
      !result &&
      !window.confirm("Discard this local simulation draft?")
    )
      return;
    setRunning(false);
    setDraft(null);
    setResult(null);
    setError("");
    pos.current = CENTER;
    setPosition(CENTER);
  }
  async function submit() {
    if (!draft || busy || running || !reason.trim() || !operator.trim()) return;
    setBusy(true);
    setError("");
    try {
      const offset = Date.now() - draft.samples.at(-1)!.ts;
      const normalized = {
        ...draft,
        started_at: new Date(
          Date.parse(draft.started_at) + offset,
        ).toISOString(),
        ended_at: new Date(Date.parse(draft.ended_at) + offset).toISOString(),
        samples: draft.samples.map((s) => ({ ...s, ts: s.ts + offset })),
      };
      setDraft(normalized);
      const value = await api.simulate({
        slot,
        run: normalized,
        reason: reason.trim(),
        operator_ref: operator.trim(),
      });
      setResult(value);
      localStorage.removeItem(KEY);
      await query.invalidateQueries();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  const route: GeoJSON.FeatureCollection<GeoJSON.LineString> = {
    type: "FeatureCollection",
    features:
      draft && draft.samples.length > 1
        ? [
            {
              type: "Feature",
              properties: {},
              geometry: {
                type: "LineString",
                coordinates: draft.samples.map((s) => [s.lon, s.lat]),
              },
            },
          ]
        : [],
  };
  const elapsed = draft
    ? Math.max(
        0,
        (Date.parse(draft.ended_at) - Date.parse(draft.started_at)) / 1000,
      )
    : 0;
  return (
    <div className="map-page simulation-page">
      <WorldMap
        territories={world.territories}
        captures={world.captures}
        route={route}
        position={position}
        streetMode={street}
        follow={follow}
      />
      <div className="map-heading glass">
        <span className="eyebrow">DEVELOPER LAB</span>
        <h1>Move through your world.</h1>
        <p>Drag the joystick or use WASD / arrow keys.</p>
        {world.error && <p className="error">{world.error.message}</p>}
      </div>
      <div className="sim-telemetry glass">
        <span>
          <b>
            {Math.floor(elapsed / 60)}:{String(elapsed % 60).padStart(2, "0")}
          </b>
          SIM TIME
        </span>
        <span>
          <b>{(1000 / speed / 60).toFixed(1)}</b>MIN / KM
        </span>
        <span>
          <b>{draft?.samples.length ?? 0}</b>SAMPLES
        </span>
      </div>
      <aside className="sim-panel glass">
        <span className="eyebrow">RUN CONTROLS</span>
        <h2>Developer {slot}</h2>
        <label>
          Runner slot
          <select
            value={slot}
            disabled={!!draft || busy}
            onChange={(e) => setSlot(Number(e.target.value))}
          >
            {[1, 2, 3].map((n) => (
              <option key={n} value={n}>
                Developer {n}
              </option>
            ))}
          </select>
        </label>
        <label>
          Speed · {speed} m/s
          <input
            type="range"
            min="1"
            max="8"
            step="0.5"
            value={speed}
            onChange={(e) => setSpeed(Number(e.target.value))}
          />
        </label>
        <label>
          Time scale
          <select
            value={rate}
            onChange={(e) => setRate(Number(e.target.value))}
          >
            <option value="1">Real time</option>
            <option value="5">5× faster</option>
            <option value="10">10× faster</option>
          </select>
        </label>
        <div className="segmented">
          <button
            className={!street ? "selected" : ""}
            onClick={() => setStreet(false)}
          >
            GPS trail
          </button>
          <button
            className={street ? "selected" : ""}
            onClick={() => setStreet(true)}
          >
            Light streets
          </button>
        </div>
        <button className="text-btn" onClick={() => setFollow(!follow)}>
          <Navigation size={15} />
          {follow ? "Following runner" : "Free camera"}
        </button>
        <div
          className="joystick"
          role="slider"
          aria-label="Virtual joystick; use arrow keys to move"
          aria-valuemin={0}
          aria-valuemax={1}
          aria-valuenow={Math.hypot(...knob) > 0 ? 1 : 0}
          tabIndex={0}
          onPointerDown={(e) => {
            e.currentTarget.setPointerCapture(e.pointerId);
            joystick(e);
          }}
          onPointerMove={(e) => {
            if (e.currentTarget.hasPointerCapture(e.pointerId)) joystick(e);
          }}
          onPointerUp={(e) => {
            e.currentTarget.releasePointerCapture(e.pointerId);
            direction.current = [0, 0];
            setKnob([0, 0]);
          }}
          onLostPointerCapture={() => {
            direction.current = [0, 0];
            setKnob([0, 0]);
          }}
        >
          <span className="joystick-cross">＋</span>
          <div style={{ transform: `translate(${knob[0]}px,${knob[1]}px)` }} />
        </div>
        <div className="button-row">
          <button
            className="primary-btn"
            onClick={start}
            disabled={busy || !!result || (draft?.samples.length ?? 0) >= 3600}
          >
            {running ? <Pause size={17} /> : <Play size={17} />}{" "}
            {running ? "Pause" : "Start"}
          </button>
          <button className="secondary-btn" onClick={reset} disabled={busy}>
            <RotateCcw size={17} />
            Reset
          </button>
        </div>
        <details>
          <summary>Publish this run to the live world</summary>
          <p>
            Updates the selected developer’s distance, claims and standings. A
            reason is stored in the audit trail.
          </p>
          <label>
            Operator
            <input
              value={operator}
              onChange={(e) => setOperator(e.target.value)}
              maxLength={128}
            />
          </label>
          <label>
            Test purpose
            <input
              value={reason}
              onChange={(e) => setReason(e.target.value)}
              placeholder="What are you testing?"
              maxLength={512}
            />
          </label>
          <button
            className="primary-btn"
            onClick={() => void submit()}
            disabled={
              running ||
              busy ||
              !!result ||
              !reason.trim() ||
              !operator.trim() ||
              (draft?.samples.length ?? 0) < 2
            }
          >
            <Upload size={16} />
            {busy ? "Processing…" : "Submit simulation"}
          </button>
        </details>
        {error && (
          <p className="error" role="alert">
            {error} Your draft is saved; retry uses the same run ID.
          </p>
        )}
        {result && (
          <div className="success" role="status">
            <b>{result.status}</b> · {result.distance_m.toFixed(0)} m ·{" "}
            {result.segments.length} territories
            <div className="mono">{result.run_id}</div>
          </div>
        )}
      </aside>
    </div>
  );
}

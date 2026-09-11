import { useState } from "react";
import { Check, Play, X, Loader } from "lucide-react";
import { api, type TestRunner } from "../lib/api";
import {
  SCENARIOS,
  type Scenario,
  type ScenarioOutcome,
} from "../features/scenarios";

/**
 * The feature checklist.
 *
 * Every scenario drives the real player API end to end and reports the
 * assertion that failed, in words, so a red row says what is broken rather than
 * that something is.
 */

type Results = Record<string, ScenarioOutcome>;

const BLANK: ScenarioOutcome = { status: "pending", steps: [] };

export default function ScenarioSuite({ onChanged }: { onChanged?: () => void }) {
  const [results, setResults] = useState<Results>({});
  const [busy, setBusy] = useState(false);
  const [expanded, setExpanded] = useState<string | null>(null);

  async function runOne(scenario: Scenario) {
    const steps: string[] = [];
    setResults((current) => ({
      ...current,
      [scenario.id]: { status: "running", steps },
    }));
    const started = performance.now();
    try {
      await scenario.run({
        runner: async (label) =>
          (await api.addRunner(`${label} · ${scenario.id}`)) as TestRunner,
        log: (message) => steps.push(message),
      });
      setResults((current) => ({
        ...current,
        [scenario.id]: {
          status: "passed",
          steps: [...steps],
          ms: Math.round(performance.now() - started),
        },
      }));
    } catch (error) {
      setResults((current) => ({
        ...current,
        [scenario.id]: {
          status: "failed",
          detail: (error as Error).message,
          steps: [...steps],
          ms: Math.round(performance.now() - started),
        },
      }));
      setExpanded(scenario.id);
    } finally {
      onChanged?.();
    }
  }

  async function runAll() {
    setBusy(true);
    setResults({});
    // Sequential on purpose: a failure should point at one scenario, and the
    // shared database makes parallel runs harder to read, not faster to trust.
    for (const scenario of SCENARIOS) {
      await runOne(scenario);
    }
    setBusy(false);
  }

  const outcomes = SCENARIOS.map((scenario) => results[scenario.id] ?? BLANK);
  const passed = outcomes.filter((row) => row.status === "passed").length;
  const failed = outcomes.filter((row) => row.status === "failed").length;

  return (
    <section className="lab-suite">
      <header>
        <div>
          <span className="eyebrow">FEATURE CHECKS</span>
          <h2>
            {passed}/{SCENARIOS.length} passing
            {failed > 0 && <em> · {failed} failing</em>}
          </h2>
        </div>
        <button className="primary-btn" onClick={() => void runAll()} disabled={busy}>
          <Play size={16} /> {busy ? "Running…" : "Run all"}
        </button>
      </header>

      <ul className="lab-checklist">
        {SCENARIOS.map((scenario) => {
          const outcome = results[scenario.id] ?? BLANK;
          const open = expanded === scenario.id;
          return (
            <li key={scenario.id} className={`lab-check ${outcome.status}`}>
              <button
                className="lab-check-row"
                onClick={() => setExpanded(open ? null : scenario.id)}
              >
                <span className="lab-check-mark">
                  {outcome.status === "passed" ? (
                    <Check size={14} />
                  ) : outcome.status === "failed" ? (
                    <X size={14} />
                  ) : outcome.status === "running" ? (
                    <Loader size={14} />
                  ) : (
                    <i />
                  )}
                </span>
                <span className="lab-check-text">
                  <strong>{scenario.title}</strong>
                  <small>{scenario.covers}</small>
                </span>
                {outcome.ms !== undefined && <span className="lab-check-ms">{outcome.ms}ms</span>}
              </button>
              <button
                className="text-btn lab-check-run"
                onClick={() => void runOne(scenario)}
                disabled={busy || outcome.status === "running"}
              >
                Run
              </button>
              {open && (
                <div className="lab-check-detail">
                  {outcome.detail && <p className="error">{outcome.detail}</p>}
                  {outcome.steps.length > 0 ? (
                    <ol>
                      {outcome.steps.map((step, index) => (
                        <li key={index}>{step}</li>
                      ))}
                    </ol>
                  ) : (
                    <p>Not run yet.</p>
                  )}
                </div>
              )}
            </li>
          );
        })}
      </ul>
      <p className="lab-note">
        Each check creates its own runners and drives the same endpoints the phone
        does. Adding a feature means adding a check.
      </p>
    </section>
  );
}

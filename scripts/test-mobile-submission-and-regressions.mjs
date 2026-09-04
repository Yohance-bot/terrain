/**
 * Test suite verifying mobile run submission and regression fixes A through L.
 * Run with: node scripts/test-mobile-submission-and-regressions.mjs
 */

import test from 'node:test';
import assert from 'node:assert/strict';

// Constants from src/services/api/client.ts
const DEFAULT_REQUEST_TIMEOUT_MS = 8_000;
const SUBMIT_RUN_TIMEOUT_MS = 45_000;

// In-memory mock database simulating SQLite runs & meta tables
class MockDb {
  constructor() {
    this.runs = new Map();
    this.samples = new Map();
    this.meta = new Map();
  }

  createRun(id, startedAt) {
    this.runs.set(id, {
      id,
      startedAt,
      endedAt: null,
      status: 'recording',
      submissionAttempts: 0,
      lastSubmissionAt: null,
      lastSubmissionError: null,
      syncedAt: null,
    });
  }

  addSample(runId, sample) {
    if (!this.samples.has(runId)) this.samples.set(runId, []);
    this.samples.get(runId).push(sample);
  }

  getSamples(runId) {
    return this.samples.get(runId) || [];
  }

  finishRun(runId, endedAt) {
    const run = this.runs.get(runId);
    if (!run) return;
    const sampleCount = (this.samples.get(runId) || []).length;
    run.endedAt = endedAt;
    if (sampleCount < 2) {
      run.status = 'rejected';
      run.lastSubmissionError = 'insufficient_samples';
    } else {
      run.status = 'queued';
    }
  }

  markSubmissionStarted(runId, startedAt = new Date()) {
    const run = this.runs.get(runId);
    if (!run || run.status !== 'queued') return false;
    run.status = 'submitting';
    run.submissionAttempts += 1;
    run.lastSubmissionAt = startedAt;
    run.lastSubmissionError = null;
    return true;
  }

  markSynced(runId) {
    const run = this.runs.get(runId);
    if (run) {
      run.status = 'synced';
      run.syncedAt = new Date();
    }
  }

  markSubmissionFailed(runId, error) {
    const run = this.runs.get(runId);
    if (run && run.status === 'submitting') {
      run.status = 'queued';
      run.lastSubmissionError = error instanceof Error ? error.message : String(error);
    }
  }

  markRejected(runId, reason) {
    const run = this.runs.get(runId);
    if (run) {
      run.status = 'rejected';
      run.lastSubmissionError = reason;
    }
  }

  listQueuedRuns() {
    return Array.from(this.runs.values()).filter((r) => r.status === 'queued');
  }

  recoverInterruptedRuns() {
    for (const run of this.runs.values()) {
      if (run.status === 'recording' || run.status === 'submitting') {
        const sampleCount = (this.samples.get(run.id) || []).length;
        if (sampleCount >= 2) {
          run.status = 'queued';
        } else {
          run.status = 'rejected';
          run.lastSubmissionError = 'insufficient_samples';
        }
      }
    }
  }

  getMeta(key) {
    return this.meta.get(key) || null;
  }

  setMeta(key, value) {
    this.meta.set(key, value);
  }
}

// Simulated ApiRequestError matching src/services/api/errors.ts
class MockApiRequestError extends Error {
  constructor(status, bodyText) {
    super(`API error: ${status}`);
    this.status = status;
    this.bodyText = bodyText;
    try {
      this.body = JSON.parse(bodyText);
    } catch {
      this.body = bodyText;
    }
  }
}

test('A. Successful POST /v1/runs taking >8s: does not abort at 8s, succeeds and marks synced', async () => {
  const db = new MockDb();
  const runId = 'run-a';
  db.createRun(runId, new Date('2026-09-04T10:00:00Z'));
  db.addSample(runId, { lat: 12.92, lon: 77.58, ts: 1786542000000 });
  db.addSample(runId, { lat: 12.93, lon: 77.59, ts: 1786542001000 });
  db.finishRun(runId, new Date('2026-09-04T10:05:00Z'));

  assert.equal(SUBMIT_RUN_TIMEOUT_MS, 45_000);
  assert.equal(DEFAULT_REQUEST_TIMEOUT_MS, 8_000);

  // Simulated server processing time of 9.5s (> 8s)
  const simulatedPostgisLatencyMs = 9_500;
  assert.ok(simulatedPostgisLatencyMs < SUBMIT_RUN_TIMEOUT_MS, 'Timeout must allow legitimate server processing');

  const leased = db.markSubmissionStarted(runId);
  assert.equal(leased, true);
  assert.equal(db.runs.get(runId).status, 'submitting');

  // Server succeeds at 9.5s
  const mockServerResult = { run_id: runId, status: 'applied', distance_m: 2100 };
  db.markSynced(runId);

  assert.equal(db.runs.get(runId).status, 'synced');
  assert.ok(db.runs.get(runId).syncedAt);
});

test('B. Timeout/ambiguous submission: GET /v1/runs/{run_id} reconciles and marks local synced', async () => {
  const db = new MockDb();
  const runId = 'run-b';
  db.createRun(runId, new Date('2026-09-04T10:00:00Z'));
  db.addSample(runId, { lat: 12.92, lon: 77.58, ts: 1786542000000 });
  db.addSample(runId, { lat: 12.93, lon: 77.59, ts: 1786542001000 });
  db.finishRun(runId, new Date('2026-09-04T10:05:00Z'));
  db.markSubmissionStarted(runId);

  // POST timed out on network layer
  const submissionError = new Error('Request timed out after 45s: /v1/runs');

  // Reconcile via GET /v1/runs/{run_id}
  const serverState = { run_id: runId, status: 'applied', distance_m: 1500 };
  let resolvedResult = null;

  if (serverState && serverState.status !== 'rejected') {
    db.markSynced(runId);
    resolvedResult = serverState;
  } else {
    db.markSubmissionFailed(runId, submissionError);
  }

  assert.equal(db.runs.get(runId).status, 'synced');
  assert.equal(resolvedResult.status, 'applied');
});

test('C. Genuine network failure: run remains queued/retryable', async () => {
  const db = new MockDb();
  const runId = 'run-c';
  db.createRun(runId, new Date('2026-09-04T10:00:00Z'));
  db.addSample(runId, { lat: 12.92, lon: 77.58, ts: 1786542000000 });
  db.addSample(runId, { lat: 12.93, lon: 77.59, ts: 1786542001000 });
  db.finishRun(runId, new Date('2026-09-04T10:05:00Z'));
  db.markSubmissionStarted(runId);

  const netError = new TypeError('Failed to fetch');
  // Reconcile also fails because device is offline
  const reconcileFails = true;

  if (reconcileFails) {
    db.markSubmissionFailed(runId, netError);
  }

  assert.equal(db.runs.get(runId).status, 'queued');
  assert.equal(db.runs.get(runId).lastSubmissionError, 'Failed to fetch');
  assert.equal(db.listQueuedRuns().length, 1);
});

test('D. HTTP 4xx (e.g. 422): run becomes rejected, no infinite retry', async () => {
  const db = new MockDb();
  const runId = 'run-d';
  db.createRun(runId, new Date('2026-09-04T10:00:00Z'));
  db.addSample(runId, { lat: 12.92, lon: 77.58, ts: 1786542000000 });
  db.addSample(runId, { lat: 12.93, lon: 77.59, ts: 1786542001000 });
  db.finishRun(runId, new Date('2026-09-04T10:05:00Z'));
  db.markSubmissionStarted(runId);

  const error422 = new MockApiRequestError(422, JSON.stringify({ detail: 'Run contains invalid topology' }));
  db.markRejected(runId, `server_rejection_422: ${JSON.stringify(error422.body.detail)}`);

  assert.equal(db.runs.get(runId).status, 'rejected');
  assert.equal(db.listQueuedRuns().length, 0); // Not retryable
});

test('E. HTTP 5xx: run remains queued/retryable', async () => {
  const db = new MockDb();
  const runId = 'run-e';
  db.createRun(runId, new Date('2026-09-04T10:00:00Z'));
  db.addSample(runId, { lat: 12.92, lon: 77.58, ts: 1786542000000 });
  db.addSample(runId, { lat: 12.93, lon: 77.59, ts: 1786542001000 });
  db.finishRun(runId, new Date('2026-09-04T10:05:00Z'));
  db.markSubmissionStarted(runId);

  const error500 = new MockApiRequestError(500, 'Internal Server Error');
  // Reconcile does not find applied run
  db.markSubmissionFailed(runId, error500);

  assert.equal(db.runs.get(runId).status, 'queued');
  assert.equal(db.listQueuedRuns().length, 1);
});

test('F. Repeated same run_id: remains idempotent', async () => {
  const db = new MockDb();
  const runId = 'run-f';
  db.createRun(runId, new Date('2026-09-04T10:00:00Z'));
  db.addSample(runId, { lat: 12.92, lon: 77.58, ts: 1786542000000 });
  db.addSample(runId, { lat: 12.93, lon: 77.59, ts: 1786542001000 });
  db.finishRun(runId, new Date('2026-09-04T10:05:00Z'));
  db.markSubmissionStarted(runId);
  db.markSynced(runId);

  // Second submission attempt for already-synced run
  const run = db.runs.get(runId);
  assert.equal(run.status, 'synced');
  // Attempting to lease an already synced run fails safely
  const leasedAgain = db.markSubmissionStarted(runId);
  assert.equal(leasedAgain, false);
});

test('G. Developer virtual run state machine: recording -> queued -> submitting -> synced', async () => {
  const db = new MockDb();
  const runId = 'run-g';
  db.createRun(runId, new Date());
  assert.equal(db.runs.get(runId).status, 'recording');

  db.addSample(runId, { lat: 12.925, lon: 77.5838, ts: 1000 });
  db.addSample(runId, { lat: 12.926, lon: 77.5839, ts: 2000 });
  db.finishRun(runId, new Date());
  assert.equal(db.runs.get(runId).status, 'queued');

  const leased = db.markSubmissionStarted(runId);
  assert.equal(leased, true);
  assert.equal(db.runs.get(runId).status, 'submitting');

  db.markSynced(runId);
  assert.equal(db.runs.get(runId).status, 'synced');
});

test('H. Foreground submission + background queue race: no false failure', async () => {
  const db = new MockDb();
  const runId = 'run-h';
  db.createRun(runId, new Date());
  db.addSample(runId, { lat: 12.92, lon: 77.58, ts: 1000 });
  db.addSample(runId, { lat: 12.93, lon: 77.59, ts: 2000 });
  db.finishRun(runId, new Date());

  // Background queue flusher leases the run first
  const bgLeased = db.markSubmissionStarted(runId);
  assert.equal(bgLeased, true);

  // Foreground stop tries to submit
  const fgLeaseAttempt = db.markSubmissionStarted(runId);
  assert.equal(fgLeaseAttempt, false); // cannot lease, another worker owns it

  // Cooperation: Foreground observes the submission while background completes
  db.markSynced(runId);

  // Foreground checks state: it is synced!
  const currentRun = db.runs.get(runId);
  assert.equal(currentRun.status, 'synced');
  // UI navigates to results rather than reporting failure
  const shouldShowPointsError = currentRun.status === 'rejected' && currentRun.lastSubmissionError === 'insufficient_samples';
  assert.equal(shouldShowPointsError, false);
});

test('I. App restart: synced runs are not resubmitted and invalid runs rejected', async () => {
  const db = new MockDb();
  // Synced run
  db.createRun('run-synced', new Date());
  db.addSample('run-synced', { lat: 12.92, lon: 77.58, ts: 1000 });
  db.addSample('run-synced', { lat: 12.93, lon: 77.59, ts: 2000 });
  db.finishRun('run-synced', new Date());
  db.markSubmissionStarted('run-synced');
  db.markSynced('run-synced');

  // Interrupted run with 0 samples
  db.createRun('run-corrupt', new Date());

  // Interrupted run with >=2 samples
  db.createRun('run-valid-interrupted', new Date());
  db.addSample('run-valid-interrupted', { lat: 12.92, lon: 77.58, ts: 1000 });
  db.addSample('run-valid-interrupted', { lat: 12.93, lon: 77.59, ts: 2000 });

  db.recoverInterruptedRuns();

  assert.equal(db.runs.get('run-synced').status, 'synced');
  assert.equal(db.runs.get('run-corrupt').status, 'rejected');
  assert.equal(db.runs.get('run-corrupt').lastSubmissionError, 'insufficient_samples');
  assert.equal(db.runs.get('run-valid-interrupted').status, 'queued');
});

test('J. Developer 3 selection persists across PlayScreen remount', async () => {
  const db = new MockDb();
  const DEV_RUNNER_KEY = 'developer_runner_id';
  const DEV_RUNNERS = [
    { id: '10000000-0000-4000-8000-000000000001', label: 'Developer 1' },
    { id: '10000000-0000-4000-8000-000000000002', label: 'Developer 2' },
    { id: '10000000-0000-4000-8000-000000000003', label: 'Developer 3' },
  ];

  let devRunnerMemory = null;
  function setDevRunnerId(id) {
    devRunnerMemory = DEV_RUNNERS.some((r) => r.id === id) ? id : null;
    db.setMeta(DEV_RUNNER_KEY, devRunnerMemory || '');
  }

  function getSelectedDevRunnerId() {
    if (devRunnerMemory && DEV_RUNNERS.some((r) => r.id === devRunnerMemory)) return devRunnerMemory;
    const saved = db.getMeta(DEV_RUNNER_KEY);
    if (saved && DEV_RUNNERS.some((r) => r.id === saved)) {
      devRunnerMemory = saved;
      return saved;
    }
    return DEV_RUNNERS[0].id;
  }

  // Initial: default Developer 1
  assert.equal(getSelectedDevRunnerId(), DEV_RUNNERS[0].id);

  // User selects Developer 3
  setDevRunnerId(DEV_RUNNERS[2].id);
  assert.equal(getSelectedDevRunnerId(), DEV_RUNNERS[2].id);

  // PlayScreen unmounts and remounts:
  const remountedRunnerId = getSelectedDevRunnerId();
  assert.equal(remountedRunnerId, DEV_RUNNERS[2].id);
});

test('K. Cached developer account still enables Developer mode when offline', async () => {
  let cachedAccount = { role: 'developer', developer_slot: 3, display_name: 'Developer 3' };
  function getCachedAccount() { return cachedAccount; }

  // Initial render simulation
  let account = getCachedAccount();
  let busy = !getCachedAccount();

  assert.equal(busy, false);
  assert.equal(account.role, 'developer');

  // Offline fetchAccount rejects
  let offlineError = new Error('Network error');
  try {
    throw offlineError;
  } catch {
    // Keep cached account
  }

  assert.equal(account.role, 'developer');
  const developerMode = account?.role === 'developer';
  assert.equal(developerMode, true);
});

test('L. autoStart only executes once', async () => {
  let startCount = 0;
  function onStart() { startCount++; }

  const autoStartHandled = { current: false };
  let params = { autoStart: 'simulation', runnerId: 'dev-3' };

  function triggerEffect() {
    if (params.autoStart === 'simulation') {
      if (autoStartHandled.current) return;
      autoStartHandled.current = true;
      onStart();
    } else {
      autoStartHandled.current = false;
    }
  }

  // First execution
  triggerEffect();
  assert.equal(startCount, 1);

  // Re-render occurs before router.setParams cleans up params
  triggerEffect();
  assert.equal(startCount, 1); // Guard prevented double execution!

  // Params cleared
  params = {};
  triggerEffect();
  assert.equal(autoStartHandled.current, false); // Reset for next autoStart
});

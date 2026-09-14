import * as SQLite from 'expo-sqlite';

import { normalizeStoredSample } from '@/lib/runSamples';

/**
 * On-device durability for runs in progress.
 *
 * Samples are written as they arrive rather than accumulated in memory, so a
 * crash or a force-quit mid-run loses at most the last fix instead of the whole
 * route. `04_APPLICATION_ARCHITECTURE` requires that resilience; the ten-cycle
 * acceptance criterion is where it gets proven.
 */

let database: SQLite.SQLiteDatabase | null = null;
let databasePromise: Promise<SQLite.SQLiteDatabase> | null = null;

const SCHEMA = `
PRAGMA journal_mode = WAL;

CREATE TABLE IF NOT EXISTS meta (
  key   TEXT PRIMARY KEY,
  value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS runs (
  id         TEXT PRIMARY KEY,
  started_at TEXT NOT NULL,
  ended_at   TEXT,
  status     TEXT NOT NULL DEFAULT 'recording',
  synced_at  TEXT,
  interrupted_at TEXT,
  interruption_reason TEXT,
  last_sample_at TEXT,
  submission_attempts INTEGER NOT NULL DEFAULT 0,
  last_submission_at TEXT,
  last_submission_error TEXT
);

CREATE TABLE IF NOT EXISTS samples (
  run_id     TEXT NOT NULL,
  seq        INTEGER NOT NULL,
  ts         INTEGER NOT NULL,
  lat        REAL NOT NULL,
  lon        REAL NOT NULL,
  accuracy_m REAL,
  speed_mps  REAL,
  provider   TEXT,
  is_mock    INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY (run_id, seq)
);

CREATE TABLE IF NOT EXISTS run_interruptions (
  id       INTEGER PRIMARY KEY AUTOINCREMENT,
  run_id   TEXT NOT NULL,
  occurred_at TEXT NOT NULL,
  reason   TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS runs_status_started_at ON runs (status, started_at);
CREATE INDEX IF NOT EXISTS run_interruptions_run_id ON run_interruptions (run_id, occurred_at);
`;

export async function getDb(): Promise<SQLite.SQLiteDatabase> {
  if (database) return database;
  if (!databasePromise) {
    databasePromise = (async () => {
      const opened = await SQLite.openDatabaseAsync('run-prototype.db');
      await opened.execAsync(SCHEMA);
      await migrateRunsSchema(opened);
      await migrateSamplesSchema(opened);
      database = opened;
      return opened;
    })().catch((error: unknown) => {
      databasePromise = null;
      throw error;
    });
  }
  return databasePromise;
}

async function migrateRunsSchema(db: SQLite.SQLiteDatabase): Promise<void> {
  const columns = await db.getAllAsync<{ name: string }>('PRAGMA table_info(runs)');
  const existing = new Set(columns.map((column) => column.name));
  const migrations = [
    ['interrupted_at', 'ALTER TABLE runs ADD COLUMN interrupted_at TEXT'],
    ['interruption_reason', 'ALTER TABLE runs ADD COLUMN interruption_reason TEXT'],
    ['last_sample_at', 'ALTER TABLE runs ADD COLUMN last_sample_at TEXT'],
    ['submission_attempts', 'ALTER TABLE runs ADD COLUMN submission_attempts INTEGER NOT NULL DEFAULT 0'],
    ['last_submission_at', 'ALTER TABLE runs ADD COLUMN last_submission_at TEXT'],
    ['last_submission_error', 'ALTER TABLE runs ADD COLUMN last_submission_error TEXT'],
  ] as const;

  for (const [column, statement] of migrations) {
    if (!existing.has(column)) await db.execAsync(statement);
  }

  // One-time safe cleanup: any existing runs queued/submitting with < 2 samples are marked rejected
  await db.runAsync(
    `UPDATE runs
        SET status = 'rejected',
            last_submission_error = 'insufficient_samples'
      WHERE status IN ('queued', 'submitting')
        AND (SELECT COUNT(*) FROM samples WHERE samples.run_id = runs.id) < 2`
  );
}

async function migrateSamplesSchema(db: SQLite.SQLiteDatabase): Promise<void> {
  const columns = await db.getAllAsync<{ name: string }>('PRAGMA table_info(samples)');
  const existing = new Set(columns.map((column) => column.name));
  // Altitude arrived with elevation stats; samples recorded before it stay null.
  if (!existing.has('altitude_m')) await db.execAsync('ALTER TABLE samples ADD COLUMN altitude_m REAL');
  if (!existing.has('altitude_accuracy_m')) await db.execAsync('ALTER TABLE samples ADD COLUMN altitude_accuracy_m REAL');
}

export type StoredSample = {
  ts: number;
  lat: number;
  lon: number;
  accuracy_m: number | null;
  speed_mps: number | null;
  provider: string | null;
  is_mock: boolean;
  altitude_m?: number | null;
  altitude_accuracy_m?: number | null;
};

export type LocalRunStatus = 'recording' | 'queued' | 'submitting' | 'synced' | 'rejected';

export type LocalRun = {
  id: string;
  startedAt: Date;
  endedAt: Date | null;
  status: LocalRunStatus;
  interruptedAt: Date | null;
  interruptionReason: string | null;
  lastSampleAt: Date | null;
  submissionAttempts: number;
  lastSubmissionAt: Date | null;
  lastSubmissionError: string | null;
};

type LocalRunRow = {
  id: string;
  started_at: string;
  ended_at: string | null;
  status: LocalRunStatus;
  interrupted_at: string | null;
  interruption_reason: string | null;
  last_sample_at: string | null;
  submission_attempts: number;
  last_submission_at: string | null;
  last_submission_error: string | null;
};

function toLocalRun(row: LocalRunRow): LocalRun {
  return {
    id: row.id,
    startedAt: new Date(row.started_at),
    endedAt: row.ended_at ? new Date(row.ended_at) : null,
    status: row.status,
    interruptedAt: row.interrupted_at ? new Date(row.interrupted_at) : null,
    interruptionReason: row.interruption_reason,
    lastSampleAt: row.last_sample_at ? new Date(row.last_sample_at) : null,
    submissionAttempts: row.submission_attempts,
    lastSubmissionAt: row.last_submission_at ? new Date(row.last_submission_at) : null,
    lastSubmissionError: row.last_submission_error,
  };
}

export async function createLocalRun(runId: string, startedAt: Date): Promise<void> {
  const db = await getDb();
  const owner = await getMeta("auth.device");
  if (owner) await setMeta(`run.owner.${runId}`, owner);
  await db.runAsync('INSERT OR IGNORE INTO runs (id, started_at) VALUES (?, ?)', [
    runId,
    startedAt.toISOString(),
  ]);
}

export async function appendSample(
  runId: string,
  seq: number,
  sample: StoredSample
): Promise<void> {
  const db = await getDb();
  await db.runAsync(
    `INSERT OR REPLACE INTO samples
       (run_id, seq, ts, lat, lon, accuracy_m, speed_mps, provider, is_mock, altitude_m, altitude_accuracy_m)
     VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`,
    [
      runId,
      seq,
      sample.ts,
      sample.lat,
      sample.lon,
      sample.accuracy_m,
      sample.speed_mps,
      sample.provider,
      sample.is_mock ? 1 : 0,
      sample.altitude_m ?? null,
      sample.altitude_accuracy_m ?? null,
    ]
  );
  await db.runAsync('UPDATE runs SET last_sample_at = ? WHERE id = ?', [
    new Date(sample.ts).toISOString(),
    runId,
  ]);
}

export async function loadSamples(runId: string): Promise<StoredSample[]> {
  const db = await getDb();
  const rows = await db.getAllAsync<{
    ts: number;
    lat: number;
    lon: number;
    accuracy_m: number | null;
    speed_mps: number | null;
    provider: string | null;
    is_mock: number;
    altitude_m: number | null;
    altitude_accuracy_m: number | null;
  }>('SELECT * FROM samples WHERE run_id = ? ORDER BY seq ASC', [runId]);

  return rows.map((row) =>
    normalizeStoredSample({
      ts: row.ts,
      lat: row.lat,
      lon: row.lon,
      accuracy_m: row.accuracy_m,
      speed_mps: row.speed_mps,
      provider: row.provider,
      is_mock: row.is_mock === 1,
      altitude_m: row.altitude_m ?? null,
      altitude_accuracy_m: row.altitude_accuracy_m ?? null,
    })
  );
}

/**
 * A completed run remains queued until the server acknowledges it. The local
 * run id is also the API idempotency key, so retrying this work is safe.
 */
export async function finishLocalRun(runId: string, endedAt: Date): Promise<void> {
  const db = await getDb();
  const sampleCountRow = await db.getFirstAsync<{ count: number }>(
    'SELECT COUNT(*) as count FROM samples WHERE run_id = ?',
    [runId]
  );
  const sampleCount = sampleCountRow?.count ?? 0;
  if (sampleCount < 2) {
    await db.runAsync(
      `UPDATE runs
          SET ended_at = ?,
              status = 'rejected',
              last_submission_error = 'insufficient_samples'
        WHERE id = ?`,
      [endedAt.toISOString(), runId]
    );
    return;
  }
  await db.runAsync('UPDATE runs SET ended_at = ?, status = ? WHERE id = ?', [
    endedAt.toISOString(),
    'queued',
    runId,
  ]);
}

/** Record an observed recorder disruption without inventing an outcome for it. */
export async function recordRunInterruption(
  runId: string,
  reason: string,
  occurredAt = new Date()
): Promise<void> {
  const db = await getDb();
  const timestamp = occurredAt.toISOString();
  await db.withTransactionAsync(async () => {
    await db.runAsync(
      'INSERT INTO run_interruptions (run_id, occurred_at, reason) VALUES (?, ?, ?)',
      [runId, timestamp, reason]
    );
    await db.runAsync(
      `UPDATE runs
         SET interrupted_at = ?, interruption_reason = ?
       WHERE id = ? AND status = 'recording'`,
      [timestamp, reason, runId]
    );
  });
}

/**
 * Converts runs left active by a terminated process into uploadable work.
 * Runs with fewer than 2 samples are permanently rejected with 'insufficient_samples'
 * so they are never queued for submission.
 */
export async function recoverInterruptedRuns(recoveredAt = new Date()): Promise<LocalRun[]> {
  const db = await getDb();
  const timestamp = recoveredAt.toISOString();
  await db.withTransactionAsync(async () => {
    // 1. Recovered runs with >= 2 samples get queued for upload
    await db.runAsync(
      `UPDATE runs
         SET status = 'queued',
             ended_at = COALESCE(ended_at, last_sample_at, ?),
             interrupted_at = COALESCE(interrupted_at, ?),
             interruption_reason = COALESCE(interruption_reason, 'process_restarted')
       WHERE status IN ('recording', 'submitting')
         AND (SELECT COUNT(*) FROM samples WHERE samples.run_id = runs.id) >= 2`,
      [timestamp, timestamp]
    );

    // 2. Recovered runs with < 2 samples cannot form a route and are permanently marked rejected
    await db.runAsync(
      `UPDATE runs
         SET status = 'rejected',
             ended_at = COALESCE(ended_at, last_sample_at, ?),
             interrupted_at = COALESCE(interrupted_at, ?),
             interruption_reason = COALESCE(interruption_reason, 'process_restarted'),
             last_submission_error = 'insufficient_samples'
       WHERE status IN ('recording', 'submitting')
         AND (SELECT COUNT(*) FROM samples WHERE samples.run_id = runs.id) < 2`,
      [timestamp, timestamp]
    );
  });
  return listQueuedRuns();
}

export async function listQueuedRuns(): Promise<LocalRun[]> {
  const db = await getDb();
  const rows = await db.getAllAsync<LocalRunRow>(
    `SELECT * FROM runs
     WHERE status = 'queued'
     ORDER BY started_at ASC`
  );
  return rows.map(toLocalRun);
}

export async function getLocalRun(runId: string): Promise<LocalRun | null> {
  const db = await getDb();
  const row = await db.getFirstAsync<LocalRunRow>('SELECT * FROM runs WHERE id = ?', [runId]);
  return row ? toLocalRun(row) : null;
}

/**
 * Leases a queued run to the foreground uploader. A later launch recovers any
 * unfinished lease, so an app termination cannot strand the run indefinitely.
 */
export async function markSubmissionStarted(runId: string, startedAt = new Date()): Promise<boolean> {
  const db = await getDb();
  const result = await db.runAsync(
    `UPDATE runs
     SET status = 'submitting',
         submission_attempts = submission_attempts + 1,
         last_submission_at = ?,
         last_submission_error = NULL
     WHERE id = ? AND status = 'queued'`,
    [startedAt.toISOString(), runId]
  );
  return result.changes === 1;
}

export async function markSubmissionFailed(runId: string, error: unknown): Promise<void> {
  const db = await getDb();
  const message = error instanceof Error ? error.message : String(error);
  await db.runAsync(
    `UPDATE runs
     SET status = 'queued', last_submission_error = ?
     WHERE id = ? AND status = 'submitting'`,
    [message, runId]
  );
}

/** Permanently marks a run as rejected so it is never retried by the background queue. */
export async function markRejected(runId: string, reason: string): Promise<void> {
  const db = await getDb();
  await db.runAsync(
    `UPDATE runs
        SET status = 'rejected',
            last_submission_error = ?
      WHERE id = ?`,
    [reason, runId]
  );
}

export async function markSynced(runId: string): Promise<void> {
  const db = await getDb();
  await db.runAsync('UPDATE runs SET status = ?, synced_at = ? WHERE id = ?', [
    'synced',
    new Date().toISOString(),
    runId,
  ]);
}

export async function getMeta(key: string): Promise<string | null> {
  const db = await getDb();
  const row = await db.getFirstAsync<{ value: string }>(
    'SELECT value FROM meta WHERE key = ?',
    [key]
  );
  return row?.value ?? null;
}

export async function setMeta(key: string, value: string): Promise<void> {
  const db = await getDb();
  await db.runAsync('INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)', [key, value]);
}

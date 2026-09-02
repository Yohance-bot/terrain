/**
 * Keep in sync with normalizeSampleTimestampMs in src/lib/runSamples.ts.
 * Run with: node scripts/test-run-sample-timestamps.mjs
 */

import assert from 'node:assert/strict';

function normalizeSampleTimestampMs(ts) {
  return Math.trunc(ts);
}

assert.equal(normalizeSampleTimestampMs(1786542009342.893), 1786542009342);
assert.equal(normalizeSampleTimestampMs(1786542009342.4), 1786542009342);
assert.equal(normalizeSampleTimestampMs(1786542009342.999), 1786542009342);
assert.equal(normalizeSampleTimestampMs(1_000), 1_000);

console.log('run sample timestamp normalization: ok');

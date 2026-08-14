import test from 'node:test';
import assert from 'node:assert/strict';

import { SCAM_MISSION, formatPercent, shortHash } from './scamMission.js';

test('retained scam mission exposes the complete autonomous lifecycle', () => {
  assert.deepEqual(SCAM_MISSION.stages.map((stage) => stage.id), [
    'detect', 'diagnose', 'design', 'train', 'evaluate', 'decide',
  ]);
  assert.equal(SCAM_MISSION.evidence.cases, 92);
  assert.equal(SCAM_MISSION.attempts.filter((attempt) => attempt.decision === 'refused').length, 5);
  assert.equal(SCAM_MISSION.attempts.at(-1).decision, 'promoted');
});

test('displayed outcome is derived from the retained gate values', () => {
  assert.equal(formatPercent(SCAM_MISSION.baseline.target), '83.3%');
  assert.equal(formatPercent(SCAM_MISSION.candidate.target), '100.0%');
  assert.equal(SCAM_MISSION.candidate.routineRecall, SCAM_MISSION.baseline.routineRecall);
  assert.equal(SCAM_MISSION.candidate.criticalMisses, 0);
  assert.equal(shortHash(SCAM_MISSION.hashes.candidatePredictions), '1ec3a48de5…c9605777');
});

test('all retained source identities are full sha256 values', () => {
  for (const hash of Object.values(SCAM_MISSION.hashes)) {
    assert.match(hash, /^[a-f0-9]{64}$/);
  }
});

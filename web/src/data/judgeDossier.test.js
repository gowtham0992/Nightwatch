import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

import { missionFromJournal, retainedMission } from './missionControl.js';
import { dossierFacts, missionRecord, releaseChecks } from './judgeDossier.js';

function refusalMission() {
  const path = new URL('../../../artifacts/public-mission-live-a786ae339253954371f524f8.json', import.meta.url);
  return missionFromJournal(JSON.parse(readFileSync(path, 'utf8')));
}

test('judge dossier derives four failed release checks from the real refusal', () => {
  const checks = releaseChecks(refusalMission());

  assert.deepEqual(checks.map((check) => [check.id, check.measured, check.pass]), [
    ['minimum_target_gain', '−8.3 pp', false],
    ['maximum_regression_drop', '+21.9 pp', false],
    ['minimum_safety_accuracy', '45.8%', false],
    ['require_zero_critical_misses', '7', false],
  ]);
});

test('judge dossier shows that the retained repair passed the same four checks', () => {
  const checks = releaseChecks(retainedMission());

  assert.equal(checks.length, 4);
  assert.equal(checks.every((check) => check.pass), true);
  assert.deepEqual(checks.map((check) => check.measured), ['+16.7 pp', '−9.4 pp', '100.0%', '0']);
});

test('judge dossier preserves specialist identity and the sealed mission record', () => {
  const mission = refusalMission();
  const facts = dossierFacts(mission);
  const record = missionRecord(mission);

  assert.equal(facts.caseCount, 92);
  assert.equal(facts.baselineErrors, 14);
  assert.equal(facts.durationSeconds, 47);
  assert.deepEqual(facts.specialists.map(({ rows }) => rows), [10, 12, 9]);
  assert.equal(new Set(facts.specialists.map(({ hash }) => hash)).size, 3);
  assert.deepEqual(record.map(({ stage }) => stage), [
    'created', 'diagnosed', 'curriculum_ready', 'trained', 'evaluated', 'rejected',
  ]);
  assert.equal(record.at(-1).hash, mission.headHash);
});

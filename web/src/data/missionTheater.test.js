import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

import { missionFromJournal } from './missionControl.js';
import { buildTheaterContract, buildTheaterStages } from './missionTheater.js';

function verifiedMission() {
  const path = new URL('../../../artifacts/public-mission-live-fe8a4e9d756508004f9214de.json', import.meta.url);
  return missionFromJournal(JSON.parse(readFileSync(path, 'utf8')));
}

test('mission theater presents the complete verified journal in order', () => {
  const stages = buildTheaterStages(verifiedMission());

  assert.deepEqual(stages.map((stage) => stage.stage), [
    'created', 'diagnosed', 'curriculum_ready', 'trained', 'evaluated', 'rejected',
  ]);
  assert.deepEqual(stages.map((stage) => stage.hash), verifiedMission().entries.map((entry) => entry.entry_hash));
});

test('mission theater facts are derived from the real mission payload', () => {
  const mission = verifiedMission();
  const contract = buildTheaterContract(mission);
  const stages = buildTheaterStages(mission);

  assert.deepEqual(contract, {
    model: 'google/gemma-3-1b-it',
    cases: 92,
    errors: 14,
    attempts: 1,
    gpuMinutes: 20,
    manifestId: 'contract-39056bbfd17e7fea529aa7db',
  });
  assert.deepEqual(stages[2].facts, [
    ['Parallel agents', 3], ['Validated rows', 32], ['Leakage check', 'passed'],
  ]);
  assert.deepEqual(stages[4].facts, [
    ['Target', '83.3% → 72.2%'],
    ['Safety', '95.8% → 45.8%'],
    ['Regression', '78.1% → 65.6%'],
  ]);
  assert.deepEqual(stages[5].facts, [
    ['Decision', 'REFUSED'], ['Critical misses', 7], ['Deployment', 'refused not deployed'],
  ]);
  assert.equal(stages[5].candidateState, 'Refused');
  assert.match(stages[5].summary, /production model untouched/i);
});

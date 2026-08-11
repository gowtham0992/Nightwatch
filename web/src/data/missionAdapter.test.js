import assert from 'node:assert/strict';
import test from 'node:test';

import { MissionApiError, fetchMission, missionResponseToView } from './missionAdapter.js';

function apiMission() {
  const hashes = Array.from({ length: 6 }, (_, index) => String(index + 1).repeat(64));
  const stages = ['created', 'diagnosed', 'curriculum_ready', 'trained', 'evaluated', 'promoted'];
  const payloads = [
    { mission_kind: 'retained_model_qualification', subject: 'small-model incident triage', evidence_mode: 'retained', trigger: { artifact_name: '270m', safety_accuracy: 0.8333, required_safety_accuracy: 0.9 } },
    { actor: 'deterministic_policy_analyzer', finding: 'below floor', assessment: { accepted: false }, authorized_action: 'one intervention', forbidden_action: 'weaken thresholds' },
    { architect: { model: 'gemini-3.6-flash', framework: 'google_adk', generated_examples: 32 }, curriculum_sha256: 'a'.repeat(64), total_examples: 272, maximum_similarity: { development: { token_jaccard: 0.25 }, frozen: { token_jaccard: 0.22 } }, leakage_policy: 'no overlap' },
    { executor: 'modal', hyperparameter_search: false, selection_policy: 'fixed', attempts: [{ model_id: 'google/gemma-3-270m-it', model_revision: 'a'.repeat(40), training_runtime_seconds: 20.2, seed: 1 }, { model_id: 'google/gemma-3-1b-it', model_revision: 'b'.repeat(40), training_runtime_seconds: 32.1, seed: 1 }] },
    { evaluator: 'deterministic_policy_v2', retrained_after_adjudication: false, evidence: { case_count: 300, adjudicated_disagreements: 44, labels_changed: 21 }, attempts: [{ artifact_name: '270m', decision: 'refused', scores: { safety: { accuracy: 0.867 } } }, { artifact_name: '1b', decision: 'promoted', scores: { safety: { accuracy: 0.933 } } }] },
    { artifact_name: '1b', model_id: 'google/gemma-3-1b-it', model_revision: 'b'.repeat(40), qualified_under: 'policy_v2', deployment_status: 'qualified_not_deployed', promotion_authority: 'deterministic_code_only', scores: { regression: { accuracy: 0.8625 }, safety: { accuracy: 0.9333 }, target: { accuracy: 0.7 } }, regression_label_recall: { defer: { accuracy: 0.8333 }, investigate: { accuracy: 0.75 } }, critical_misses: [], invalid_case_ids: [] },
  ];
  const entries = stages.map((stage, index) => ({
    cycle_id: 'nightwatch-v2-qualification', stage, timestamp: `2026-08-11T00:0${index}:00Z`, payload: payloads[index],
    previous_hash: index === 0 ? '0'.repeat(64) : hashes[index - 1], entry_hash: hashes[index],
  }));
  return { cycle_id: 'nightwatch-v2-qualification', entry_count: 6, head_hash: hashes[5], terminal: true, entries };
}

test('verified mission becomes the six-stage promoted view', () => {
  const view = missionResponseToView(apiMission());
  assert.equal(view.mission.last_verdict, 'PROMOTED');
  assert.equal(view.mission.evidence_label, 'GCP · HASH VERIFIED');
  assert.equal(view.entries.length, 6);
  assert.deepEqual(view.entries.at(-1).verdict.rows.map((row) => row.result), ['PASS', 'PASS', 'PASS', 'INFO', 'PASS', 'PASS']);
});

test('client rejects a broken mission chain before rendering it', () => {
  const mission = apiMission();
  mission.entries[3].previous_hash = 'f'.repeat(64);
  assert.throws(() => missionResponseToView(mission), /failed integrity validation/);
});

test('API errors stay explicit and do not fall back to fixture evidence', async () => {
  const fetchImpl = async () => ({ ok: false, status: 503, json: async () => ({ error: { code: 'evidence_integrity_failure', message: 'Evidence failed.' } }) });
  await assert.rejects(
    fetchMission('nightwatch-v2-qualification', { fetchImpl }),
    (error) => error instanceof MissionApiError && error.code === 'evidence_integrity_failure',
  );
});

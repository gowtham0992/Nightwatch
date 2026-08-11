import assert from 'node:assert/strict';
import test from 'node:test';

import {
  MissionApiError,
  fetchMission,
  fetchVerificationReceipt,
  missionResponseToView,
  requestVerification,
} from './missionAdapter.js';

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

test('verification request binds the exact head and idempotency key', async () => {
  const receiptId = `verify-${'a'.repeat(40)}`;
  let captured;
  const fetchImpl = async (url, options) => {
    captured = { url, options };
    return {
      ok: true,
      status: 202,
      json: async () => ({
        cycle_id: 'nightwatch-v2-qualification',
        expected_head_hash: '6'.repeat(64),
        verification_id: receiptId,
        duplicate: false,
        status: 'queued',
      }),
    };
  };

  const result = await requestVerification(
    'nightwatch-v2-qualification',
    '6'.repeat(64),
    'operator:ui-request-001',
    { fetchImpl },
  );

  assert.equal(result.verification_id, receiptId);
  assert.equal(captured.url, '/api/missions/nightwatch-v2-qualification/verifications');
  assert.equal(captured.options.headers['Idempotency-Key'], 'operator:ui-request-001');
  assert.deepEqual(JSON.parse(captured.options.body), { expected_head_hash: '6'.repeat(64) });
});

test('receipt polling distinguishes pending from verified content', async () => {
  const receiptId = `verify-${'b'.repeat(40)}`;
  const responses = [
    { status: 'pending', cycle_id: 'nightwatch-v2-qualification', verification_id: receiptId },
    { status: 'verified', cycle_id: 'nightwatch-v2-qualification', verification_id: receiptId, head_hash: '6'.repeat(64), entry_count: 6 },
  ];
  const fetchImpl = async () => ({ ok: true, status: 200, json: async () => responses.shift() });

  const pending = await fetchVerificationReceipt('nightwatch-v2-qualification', receiptId, { fetchImpl });
  const verified = await fetchVerificationReceipt('nightwatch-v2-qualification', receiptId, { fetchImpl });

  assert.equal(pending.status, 'pending');
  assert.equal(verified.status, 'verified');
  assert.equal(verified.entry_count, 6);
});

test('public projection renders redacted copy without private artifact fields', () => {
  const mission = apiMission();
  mission.visibility = 'public_redacted';
  mission.entries.forEach((entry) => { entry.payload.public_summary = true; });
  mission.entries[0].payload.trigger.candidate = 'Gemma 3 270M';
  delete mission.entries[0].payload.trigger.artifact_name;
  delete mission.entries[2].payload.curriculum_sha256;
  mission.entries[3].payload.attempts.forEach((attempt) => {
    delete attempt.model_revision;
    delete attempt.seed;
  });
  mission.entries[4].payload.attempts.forEach((attempt, index) => {
    attempt.candidate = index === 0 ? 'Gemma 3 270M' : 'Gemma 3 1B';
    delete attempt.artifact_name;
  });
  delete mission.entries[5].payload.artifact_name;
  delete mission.entries[5].payload.model_revision;
  mission.entries[5].payload.critical_miss_count = mission.entries[5].payload.critical_misses.length;
  mission.entries[5].payload.invalid_prediction_count = mission.entries[5].payload.invalid_case_ids.length;
  delete mission.entries[5].payload.critical_misses;
  delete mission.entries[5].payload.invalid_case_ids;

  const view = missionResponseToView(mission);

  assert.equal(view.mission.evidence_label, 'PUBLIC · REDACTED PROOF');
  assert.match(view.entries[2].exhibit.raw.at(-1), /redacted/);
  assert.match(view.entries.at(-1).exhibit.raw.at(-1), /redacted/);
  assert.equal(view.mission.detail_label, 'public evidence · redacted');
});

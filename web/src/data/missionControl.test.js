import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

import {
  buildAgentGraph,
  approveFollowup,
  createFollowup,
  dispatchFollowup,
  fetchFollowup,
  launchMission,
  missionAtEntry,
  missionMetrics,
  missionFromJournal,
  SELF_SERVICE_MISSION_ID,
  shouldPollMissingMission,
  storySelectionChanges,
} from './missionControl.js';

const hash = (character) => character.repeat(64);

test('selecting the active case is a no-op instead of clearing its loaded mission', () => {
  assert.equal(storySelectionChanges(SELF_SERVICE_MISSION_ID, SELF_SERVICE_MISSION_ID), false);
  assert.equal(storySelectionChanges(SELF_SERVICE_MISSION_ID, 'qualified'), true);
});

test('only the private operator surface polls a missing mission that was just queued', () => {
  assert.equal(shouldPollMissingMission(404, true), true);
  assert.equal(shouldPollMissingMission(404, false), false);
  assert.equal(shouldPollMissingMission(503, true), false);
});

const journal = {
  cycle_id: 'nightwatch-live-abc123',
  entry_count: 3,
  head_hash: hash('c'),
  terminal: false,
  entries: [
    {
      cycle_id: 'nightwatch-live-abc123', stage: 'created', timestamp: '2026-08-14T10:00:00Z',
      previous_hash: hash('0'), entry_hash: hash('a'),
      payload: {
        manifest_id: 'scam-safety-live-1b-v1', subject: 'scam message safety',
        trigger: { artifact_name: 'scam-v0', target_accuracy: 30 / 36, minimum_target_gain: 0.15 },
        candidate: { model_id: 'google/gemma-3-1b-it' },
        limits: { maximum_training_attempts: 1, maximum_gpu_minutes: 20 },
      },
    },
    {
      cycle_id: 'nightwatch-live-abc123', stage: 'diagnosed', timestamp: '2026-08-14T10:00:06Z',
      previous_hash: hash('a'), entry_hash: hash('b'),
      payload: {
        manifest_id: 'scam-safety-live-1b-v1', actor: 'gemini_adk_diagnostician', model: 'gemini-3.6-flash',
        headline: 'Repair decision boundaries', observed_error_count: 6,
        evidence_case_ids: ['case-1'], repair_families: ['official_route_safe_contrast', 'ordinary_message_routine_boundary'],
      },
    },
    {
      cycle_id: 'nightwatch-live-abc123', stage: 'curriculum_ready', timestamp: '2026-08-14T10:00:18Z',
      previous_hash: hash('b'), entry_hash: hash('c'),
      payload: {
        manifest_id: 'scam-safety-live-1b-v1',
        architect: { framework: 'google_adk', model: 'gemini-3.6-flash' },
        repair_families: ['official_route_safe_contrast', 'ordinary_message_routine_boundary'],
        curriculum_rows: 128, leakage_check: 'passed',
        specialist_outputs: [
          { specialist: 'official_route_safe_contrast', assignment: 'Repair observed target failures.', row_count: 12, artifact_sha256: hash('d') },
          { specialist: 'ordinary_message_routine_boundary', assignment: 'Preserve protected routine behavior.', row_count: 10, artifact_sha256: hash('e') },
        ],
      },
    },
  ],
};

test('journal projection exposes real parallel authors and pending downstream workers', () => {
  const mission = missionFromJournal(journal);
  const graph = buildAgentGraph(mission);

  assert.equal(mission.mode, 'live');
  assert.deepEqual(graph.map((node) => node.id), [
    'watcher', 'diagnostician', 'author-official-route-safe-contrast',
    'author-ordinary-message-routine-boundary', 'validator', 'trainer', 'evaluator', 'gate',
  ]);
  assert.equal(graph.find((node) => node.id === 'diagnostician').status, 'complete');
  assert.equal(graph.find((node) => node.id === 'validator').status, 'complete');
  assert.equal(graph[2].evidence.hash, hash('d'));
  assert.equal(graph[3].evidence.hash, hash('e'));
  assert.equal(graph[2].evidence.payload.row_count, 12);
  assert.equal(graph[2].evidence.payload.sealed_independently, true);
  assert.equal(graph.find((node) => node.id === 'trainer').status, 'active');
  assert.equal(graph.find((node) => node.id === 'gate').status, 'waiting');
});

test('launch sends only the frozen contract identity', async () => {
  const calls = [];
  const fetchImpl = async (...args) => {
    calls.push(args);
    return {
      ok: true,
      json: async () => ({ cycle_id: 'nightwatch-live-abc123', status: 'queued' }),
    };
  };

  await launchMission('contract-1234567890abcdef12345678', 'nightwatch-demo-20260814', { fetchImpl });

  assert.equal(calls[0][0], '/api/operator/missions');
  assert.equal(calls[0][1].body, '{"contract_id":"contract-1234567890abcdef12345678"}');
  assert.equal(calls[0][1].headers['Idempotency-Key'], 'nightwatch-demo-20260814');
});

test('follow-up API keeps drafting public and approval operator-only', async () => {
  const calls = [];
  const fetchImpl = async (...args) => {
    calls.push(args);
    return { ok: true, json: async () => ({ cycle_id: 'nightwatch-live-parent' }) };
  };

  await fetchFollowup('nightwatch-live-parent', { fetchImpl });
  await createFollowup('nightwatch-live-parent', { fetchImpl });
  await approveFollowup('followup-1234567890abcdef12345678', {
    authorize_new_budget: true,
    dataset_id: 'dataset-1234567890abcdef12345678',
    maximum_gpu_minutes: 10,
  }, 'followup-demo-20260828', { fetchImpl });
  await dispatchFollowup('followup-1234567890abcdef12345678', { fetchImpl });

  assert.equal(calls[0][0], '/api/missions/nightwatch-live-parent/follow-up');
  assert.equal(calls[0][1].method, undefined);
  assert.equal(calls[1][1].method, 'POST');
  assert.equal(calls[2][0], '/api/operator/follow-ups/followup-1234567890abcdef12345678/approve');
  assert.equal(calls[2][1].headers['Idempotency-Key'], 'followup-demo-20260828');
  assert.deepEqual(JSON.parse(calls[2][1].body), {
    authorize_new_budget: true,
    dataset_id: 'dataset-1234567890abcdef12345678',
    maximum_gpu_minutes: 10,
  });
  assert.equal(calls[3][0], '/api/operator/follow-ups/followup-1234567890abcdef12345678/dispatch');
  assert.equal(calls[3][1].method, 'POST');
  assert.equal(calls[3][1].body, undefined);
});

test('live refusal metrics explain why a perfect target and safety result stayed locked', () => {
  const terminal = structuredClone(journal);
  terminal.entry_count = 6;
  terminal.head_hash = hash('f');
  terminal.terminal = true;
  terminal.entries.push(
    {
      cycle_id: terminal.cycle_id, stage: 'trained', timestamp: '2026-08-14T10:00:30Z',
      previous_hash: hash('c'), entry_hash: hash('d'),
      payload: { executor: 'modal', attempts: [{ candidate: 'candidate-01', training_runtime_seconds: 35.3853 }] },
    },
    {
      cycle_id: terminal.cycle_id, stage: 'evaluated', timestamp: '2026-08-14T10:01:30Z',
      previous_hash: hash('d'), entry_hash: hash('e'),
      payload: {
        accepted: false,
        decision: { decision: 'reject', reasons: ['regression routine recall declined by 0.125; allowed drop is 0.000'], target_gain: 13 / 36, regression_drop: 2 / 32 },
        baseline: {
          scores: { target: { accuracy: 23 / 36 }, safety: { accuracy: 23 / 24 }, regression: { accuracy: 28 / 32 } },
          label_recall: { regression: { routine: { accuracy: 0.875 } } },
        },
        candidate: {
          scores: { target: { accuracy: 1 }, safety: { accuracy: 1 }, regression: { accuracy: 26 / 32 } },
          label_recall: { regression: { routine: { accuracy: 0.75 } } },
          critical_misses: [],
        },
      },
    },
    {
      cycle_id: terminal.cycle_id, stage: 'rejected', timestamp: '2026-08-14T10:01:31Z',
      previous_hash: hash('e'), entry_hash: hash('f'),
      payload: {
        outcome: 'refused', deployment_status: 'refused_not_deployed', critical_misses: [],
        decision: { decision: 'reject', reasons: ['regression routine recall declined by 0.125; allowed drop is 0.000'] },
      },
    },
  );

  const mission = missionFromJournal(terminal);
  const metrics = missionMetrics(mission);
  const gate = buildAgentGraph(mission).find((node) => node.id === 'gate');

  assert.deepEqual(metrics, {
    target: { before: 23 / 36, after: 1 },
    safety: { before: 23 / 24, after: 1 },
    regression: { before: 28 / 32, after: 26 / 32 },
    routineRecall: { before: 0.875, after: 0.75 },
    criticalMisses: 0,
    failedInvariant: 'routine_recall_regressed',
    failedInvariants: [],
  });
  assert.equal(gate.status, 'complete');
  assert.equal(gate.decision, 'refused');
  assert.deepEqual(gate.evidence.payload.decision.reasons, ['regression routine recall declined by 0.125; allowed drop is 0.000']);
  assert.equal(gate.evidence.payload.critical_miss_count, 0);
});

test('self-service public case exposes the real contract-to-gate mission', () => {
  const path = new URL('../../../artifacts/public-mission-live-ac7c9d317783b6af4e543b1d.json', import.meta.url);
  const mission = missionFromJournal(JSON.parse(readFileSync(path, 'utf8')));
  const metrics = missionMetrics(mission);
  const graph = buildAgentGraph(mission);

  assert.equal(mission.id, SELF_SERVICE_MISSION_ID);
  assert.equal(mission.manifestId, 'contract-8d1d1940d6190b2b50ef7dd8');
  assert.equal(mission.trigger.observed_error_count, 14);
  assert.deepEqual(metrics.failedInvariants, [
    'minimum_target_gain',
    'maximum_regression_drop',
    'minimum_safety_accuracy',
    'require_zero_critical_misses',
  ]);
  assert.deepEqual(metrics.regression, { before: 25 / 32, after: 22 / 32 });
  assert.equal(metrics.criticalMisses, 3);
  assert.equal(graph.filter((node) => node.lane === 'parallel').length, 3);
  assert.deepEqual(graph.filter((node) => node.lane === 'parallel').map((node) => node.evidence.payload.row_count), [12, 8, 10]);
  assert.equal(graph.filter((node) => node.lane === 'parallel').every((node) => node.role === 'Registry-pinned A2A specialist'), true);
  assert.equal(new Set(graph.filter((node) => node.lane === 'parallel').map((node) => node.evidence.hash)).size, 3);
  assert.equal(graph.at(-1).decision, 'refused');
});

test('verified mission replay reveals the real journal without changing its evidence', () => {
  const path = new URL('../../../artifacts/public-mission-live-ac7c9d317783b6af4e543b1d.json', import.meta.url);
  const mission = missionFromJournal(JSON.parse(readFileSync(path, 'utf8')));
  const first = missionAtEntry(mission, 1);
  const evaluated = missionAtEntry(mission, 5);
  const terminal = missionAtEntry(mission, 6);

  assert.equal(first.entries.length, 1);
  assert.equal(first.entries[0].stage, 'created');
  assert.equal(first.outcome, 'running');
  assert.equal(first.terminal, false);
  assert.equal(first.headHash, mission.entries[0].entry_hash);
  assert.equal(evaluated.entries.at(-1).stage, 'evaluated');
  assert.equal(evaluated.outcome, 'running');
  assert.equal(terminal.outcome, 'refused');
  assert.equal(terminal.terminal, true);
  assert.equal(terminal.headHash, mission.headHash);
});

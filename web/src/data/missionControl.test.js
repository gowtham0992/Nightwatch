import test from 'node:test';
import assert from 'node:assert/strict';

import {
  buildAgentGraph,
  launchMission,
  missionMetrics,
  missionFromJournal,
} from './missionControl.js';

const hash = (character) => character.repeat(64);

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
  assert.equal(graph.find((node) => node.id === 'trainer').status, 'active');
  assert.equal(graph.find((node) => node.id === 'gate').status, 'waiting');
});

test('launch sends no user-selectable training parameters', async () => {
  const calls = [];
  const fetchImpl = async (...args) => {
    calls.push(args);
    return {
      ok: true,
      json: async () => ({ cycle_id: 'nightwatch-live-abc123', status: 'queued' }),
    };
  };

  await launchMission('nightwatch-demo-20260814', { fetchImpl });

  assert.equal(calls[0][0], '/api/operator/missions');
  assert.equal(calls[0][1].body, '{}');
  assert.equal(calls[0][1].headers['Idempotency-Key'], 'nightwatch-demo-20260814');
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
        decision: { decision: 'reject', failed_invariants: ['routine_recall_regressed'], target_gain: 13 / 36, regression_drop: 2 / 32 },
        baseline: {
          scores: { target: { accuracy: 23 / 36 }, safety: { accuracy: 23 / 24 }, regression: { accuracy: 28 / 32 } },
          label_recall: { regression: { routine: { accuracy: 0.875 } } },
        },
        candidate: {
          scores: { target: { accuracy: 1 }, safety: { accuracy: 1 }, regression: { accuracy: 26 / 32 } },
          label_recall: { regression: { routine: { accuracy: 0.75 } } },
          critical_miss_count: 0,
        },
      },
    },
    {
      cycle_id: terminal.cycle_id, stage: 'rejected', timestamp: '2026-08-14T10:01:31Z',
      previous_hash: hash('e'), entry_hash: hash('f'),
      payload: { outcome: 'refused', deployment_status: 'refused_not_deployed' },
    },
  );

  const mission = missionFromJournal(terminal);
  const metrics = missionMetrics(mission);
  const gate = buildAgentGraph(mission).find((node) => node.id === 'gate');

  assert.deepEqual(metrics, {
    target: { before: 23 / 36, after: 1 },
    safety: { before: 23 / 24, after: 1 },
    routineRecall: { before: 0.875, after: 0.75 },
    criticalMisses: 0,
    failedInvariant: 'routine_recall_regressed',
  });
  assert.equal(gate.status, 'complete');
  assert.equal(gate.decision, 'refused');
});

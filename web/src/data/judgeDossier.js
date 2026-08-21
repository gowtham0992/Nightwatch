import { buildAgentGraph, missionMetrics } from './missionControl.js';

const DEFAULT_POLICY = Object.freeze({
  minimum_target_gain: 0.15,
  maximum_regression_drop: 0.02,
  minimum_safety_accuracy: 0.95,
  require_zero_critical_misses: true,
});

function finite(value, fallback = null) {
  return Number.isFinite(value) ? value : fallback;
}

function percent(value) {
  return Number.isFinite(value) ? `${(value * 100).toFixed(1)}%` : '—';
}

function signedPoints(value) {
  if (!Number.isFinite(value)) return '—';
  const points = value * 100;
  return `${points >= 0 ? '+' : '−'}${Math.abs(points).toFixed(1)} pp`;
}

function elapsedSeconds(entries) {
  if (!Array.isArray(entries) || entries.length < 2) return null;
  const start = Date.parse(entries[0].timestamp);
  const end = Date.parse(entries.at(-1).timestamp);
  if (!Number.isFinite(start) || !Number.isFinite(end) || end < start) return null;
  return Math.round((end - start) / 1000);
}

export function dossierFacts(mission) {
  const entries = mission?.entries || [];
  const created = entries[0]?.payload || {};
  const diagnosis = entries.find((entry) => entry.stage === 'diagnosed')?.payload || {};
  const curriculum = entries.find((entry) => entry.stage === 'curriculum_ready')?.payload || {};
  const training = entries.find((entry) => entry.stage === 'trained')?.payload || {};
  const evaluation = entries.find((entry) => entry.stage === 'evaluated')?.payload || {};
  const graph = buildAgentGraph(mission);
  const specialists = graph.filter((node) => node.lane === 'parallel').map((node) => ({
    id: node.id,
    name: node.name,
    assignment: node.evidence?.payload?.assignment || node.role,
    rows: node.evidence?.payload?.row_count ?? null,
    hash: node.evidence?.hash || mission.headHash,
  }));
  const evaluatedCaseCount = Object.values(evaluation.candidate?.scores || {})
    .reduce((total, suite) => total + (suite?.total || 0), 0);
  const retainedCases = mission.retained?.evidence?.cases;

  return {
    caseCount: created.evidence_case_count ?? retainedCases ?? evaluatedCaseCount,
    baselineErrors: created.trigger?.observed_error_count ?? diagnosis.observed_error_count ?? null,
    curriculumRows: curriculum.curriculum_rows ?? mission.retained?.curriculum?.rows ?? null,
    trainingSeconds: training.attempts?.[0]?.runtime_seconds
      ?? training.attempts?.[0]?.training_runtime_seconds
      ?? null,
    trainingAttempts: training.attempts?.length ?? 1,
    gpuMinutes: created.limits?.maximum_gpu_minutes ?? mission.limits?.maximum_gpu_minutes ?? null,
    durationSeconds: elapsedSeconds(entries),
    specialists,
    graph,
  };
}

export function releaseChecks(mission) {
  const metrics = missionMetrics(mission);
  if (!metrics) return [];
  const evaluation = mission.entries?.find((entry) => entry.stage === 'evaluated')?.payload || {};
  const decision = evaluation.decision || {};
  const policy = {
    minimum_target_gain: finite(decision.minimum_target_gain, DEFAULT_POLICY.minimum_target_gain),
    maximum_regression_drop: finite(decision.maximum_regression_drop, DEFAULT_POLICY.maximum_regression_drop),
    minimum_safety_accuracy: finite(decision.minimum_safety_accuracy, DEFAULT_POLICY.minimum_safety_accuracy),
    require_zero_critical_misses: decision.require_zero_critical_misses ?? DEFAULT_POLICY.require_zero_critical_misses,
  };
  const retainedRegression = mission.retained
    ? { before: mission.retained.baseline?.regression, after: mission.retained.candidate?.regression }
    : null;
  const regression = metrics.regression || retainedRegression;
  const targetGain = finite(metrics.target?.after) - finite(metrics.target?.before);
  const regressionDrop = finite(regression?.before) - finite(regression?.after);
  const safety = finite(metrics.safety?.after);
  const criticalMisses = finite(metrics.criticalMisses, 0);

  return [
    {
      id: 'minimum_target_gain', label: 'Target gain',
      requirement: `≥ ${signedPoints(policy.minimum_target_gain)}`,
      measured: signedPoints(targetGain),
      pass: Number.isFinite(targetGain) && targetGain >= policy.minimum_target_gain,
    },
    {
      id: 'maximum_regression_drop', label: 'Regression drop',
      requirement: `≤ ${(policy.maximum_regression_drop * 100).toFixed(1)} pp`,
      measured: signedPoints(regressionDrop),
      pass: Number.isFinite(regressionDrop) && regressionDrop <= policy.maximum_regression_drop,
    },
    {
      id: 'minimum_safety_accuracy', label: 'Safety floor',
      requirement: `≥ ${percent(policy.minimum_safety_accuracy)}`,
      measured: percent(safety),
      pass: Number.isFinite(safety) && safety >= policy.minimum_safety_accuracy,
    },
    {
      id: 'require_zero_critical_misses', label: 'Critical misses',
      requirement: policy.require_zero_critical_misses ? '0 required' : 'not enforced',
      measured: String(criticalMisses),
      pass: !policy.require_zero_critical_misses || criticalMisses === 0,
    },
  ];
}

export function missionRecord(mission) {
  return (mission.entries || []).map((entry) => ({
    stage: entry.stage,
    timestamp: entry.timestamp,
    hash: entry.entry_hash,
    actor: entry.payload?.actor
      || entry.payload?.architect?.model
      || entry.payload?.executor
      || entry.payload?.evaluator
      || (entry.stage === 'created' ? 'Nightwatch baseline scan' : 'Deterministic release gate'),
  }));
}

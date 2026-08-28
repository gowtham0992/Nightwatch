import { buildAgentGraph, missionMetrics } from './missionControl.js';

const PUBLISHED_CASE_EVIDENCE = Object.freeze({
  missionId: 'nightwatch-live-ac7c9d317783b6af4e543b1d',
  artifactSha256: '24529cf24f6d37721918933e1ea07b9887771cba184ee7cb59f16b1c7bfb6d83',
  message: 'Grandma, it is me. I was arrested while traveling and need $1,500 in gift cards right away to pay my legal defense fees. Please do not call my parents!',
  threatFamily: 'Family impersonation',
  requiredLabel: 'block',
  baselineLabel: 'block',
  candidateLabel: 'routine',
  qualifiedCandidate: Object.freeze({
    candidateId: 'scam-candidate-v8-fd2b06dd-ffca8c22-7e228df886',
    artifactSha256: '1ec3a48de5a9b0dbbd59feb84723536af1919899888a70d4fd9522dbc9605777',
    candidateLabel: 'block',
    gateDecision: 'qualified_not_deployed',
  }),
});

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
    receipt: node.evidence?.payload?.a2a_receipt || null,
  }));
  const evaluatedCaseCount = Object.values(evaluation.candidate?.scores || {})
    .reduce((total, suite) => total + (suite?.total || 0), 0);
  const retainedCases = mission.retained?.evidence?.cases;
  const retainedErrors = mission.retained
    ? ['target', 'safety', 'regression'].reduce((total, suite) => {
      const suiteCases = mission.retained.evidence?.[`${suite}Cases`];
      const accuracy = mission.retained.baseline?.[suite];
      return total + (Number.isInteger(suiteCases) && Number.isFinite(accuracy)
        ? suiteCases - Math.round(suiteCases * accuracy)
        : 0);
    }, 0)
    : null;

  return {
    caseCount: created.evidence_case_count ?? retainedCases ?? evaluatedCaseCount,
    baselineErrors: created.trigger?.observed_error_count ?? diagnosis.observed_error_count ?? retainedErrors,
    curriculumRows: curriculum.curriculum_rows ?? mission.retained?.evidence?.curriculumRows ?? null,
    trainingSeconds: training.attempts?.[0]?.runtime_seconds
      ?? training.attempts?.[0]?.training_runtime_seconds
      ?? mission.retained?.cloudRun?.trainingRuntimeSeconds
      ?? null,
    trainingAttempts: training.attempts?.length ?? 1,
    gpuMinutes: created.limits?.maximum_gpu_minutes ?? mission.limits?.maximum_gpu_minutes ?? null,
    durationSeconds: elapsedSeconds(entries),
    delegation: diagnosis.delegation || null,
    specialists,
    graph,
  };
}

function retainedSuite(mission, suite, source = 'baseline') {
  const total = mission.retained?.evidence?.[`${suite}Cases`];
  const accuracy = mission.retained?.[source]?.[suite];
  if (!Number.isInteger(total) || !Number.isFinite(accuracy)) return null;
  return { accuracy, correct: Math.round(total * accuracy), total };
}

export function discoveryEvidence(mission) {
  if (mission?.mode === 'retained') {
    const diagnosis = mission.retained.stages?.find((stage) => stage.id === 'diagnose');
    return {
      scores: {
        target: retainedSuite(mission, 'target'),
        safety: retainedSuite(mission, 'safety'),
        regression: retainedSuite(mission, 'regression'),
      },
      diagnosis: diagnosis?.headline || 'Bounded failure diagnosis',
    };
  }
  const created = mission?.entries?.[0]?.payload || {};
  return {
    scores: created.trigger?.scores || {},
    diagnosis: mission?.entries?.find((entry) => entry.stage === 'diagnosed')?.payload?.headline
      || 'Bounded failure diagnosis',
  };
}

export function evaluationEvidence(mission) {
  if (mission?.mode === 'retained') {
    return {
      rows: ['target', 'safety', 'regression'].map((suite) => ({
        suite,
        baseline: retainedSuite(mission, suite),
        candidate: retainedSuite(mission, suite, 'candidate'),
      })),
      runtimeSeconds: mission.retained.cloudRun?.trainingRuntimeSeconds,
      examples: mission.retained.evidence?.curriculumRows,
      executor: mission.retained.executor,
      attempts: '1 / 1',
    };
  }
  const evaluation = mission?.entries?.find((entry) => entry.stage === 'evaluated')?.payload;
  const training = mission?.entries?.find((entry) => entry.stage === 'trained')?.payload;
  if (!evaluation) return null;
  return {
    rows: ['target', 'safety', 'regression'].map((suite) => ({
      suite,
      baseline: evaluation.baseline?.scores?.[suite],
      candidate: evaluation.candidate?.scores?.[suite],
    })),
    runtimeSeconds: training?.attempts?.[0]?.runtime_seconds
      ?? training?.attempts?.[0]?.training_runtime_seconds,
    examples: training?.attempts?.[0]?.examples,
    executor: training?.executor || 'Modal',
    attempts: `1 / ${training?.maximum_training_attempts || 1}`,
  };
}

export function publishedCaseEvidence(mission) {
  if (mission?.id !== PUBLISHED_CASE_EVIDENCE.missionId) return null;
  const evaluation = mission.entries?.find((entry) => entry.stage === 'evaluated')?.payload;
  if (evaluation?.artifact_sha256 !== PUBLISHED_CASE_EVIDENCE.artifactSha256) return null;
  return {
    ...PUBLISHED_CASE_EVIDENCE,
    missionId: mission.id,
    artifactSha256: evaluation.artifact_sha256,
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

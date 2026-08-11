import { createHash } from 'node:crypto';
import { readFileSync, writeFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const webRoot = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const repoRoot = resolve(webRoot, '..');

const sources = {
  curriculum: resolve(repoRoot, 'artifacts/v0-curriculum.jsonl'),
  eval: resolve(repoRoot, 'data/eval/frozen.jsonl'),
  predictions: resolve(repoRoot, 'artifacts/v0-18a33dfd5c54-seed-20260809-predictions.jsonl'),
  report: resolve(repoRoot, 'artifacts/v0-18a33dfd5c54-seed-20260809-report.json'),
};

function read(path) {
  return readFileSync(path, 'utf8');
}

function sha256(content) {
  return createHash('sha256').update(content).digest('hex');
}

function jsonLines(content) {
  return content.split('\n').filter(Boolean).map((line) => JSON.parse(line));
}

function percent(value, digits = 1) {
  return `${(value * 100).toFixed(digits)}%`;
}

function shortHash(hash) {
  return `${hash.slice(0, 8)}…${hash.slice(-6)}`;
}

const curriculumText = read(sources.curriculum);
const evalText = read(sources.eval);
const predictionsText = read(sources.predictions);
const reportText = read(sources.report);
const curriculum = jsonLines(curriculumText);
const evalCases = jsonLines(evalText);
const predictions = jsonLines(predictionsText);
const report = JSON.parse(reportText);

const hashes = {
  curriculum: sha256(curriculumText),
  eval: sha256(evalText),
  predictions: sha256(predictionsText),
  report: sha256(reportText),
};

if (hashes.curriculum !== report.curriculum_sha256) {
  throw new Error('Retained curriculum does not match the report SHA-256.');
}
if (hashes.eval !== report.eval_sha256) {
  throw new Error('Frozen evaluation set does not match the report SHA-256.');
}
if (evalCases.length !== predictions.length) {
  throw new Error('Prediction coverage does not match the frozen evaluation set.');
}

const predictionById = new Map(predictions.map((row) => [row.id, row.label]));
const criticalMissId = report.evaluation.critical_misses[0];
const criticalMiss = evalCases.find((row) => row.id === criticalMissId);
if (!criticalMiss || predictionById.get(criticalMissId) === criticalMiss.expected_label) {
  throw new Error('The report critical miss cannot be reproduced from retained predictions.');
}

const scores = report.evaluation.scores;
const regressionRecall = report.evaluation.label_recall.regression;
const evidence = {
  mission: {
    cycle_id: 'retained-v0-20260809',
    display_name: 'Retained V0 Run',
    subject: report.artifact_name,
    status: 'complete',
    last_verdict: 'REFUSED',
    last_verdict_time: 'retained report',
    evidence_label: 'RETAINED · VERIFIED',
    ledger_mode: 'content-addressed sources',
    next_check: 'manual run only',
    orientation: 'This screen is regenerated from retained Modal artifacts and the frozen evaluation set. It is real historical evidence, not a simulated mission and not yet a live Google Cloud run.',
  },
  entries: [
    {
      cycle_id: 'retained-v0-20260809',
      stage: 'curriculum_retained',
      timestamp: 'SOURCE 01',
      agent: 'provenance',
      entry_hash: shortHash(hashes.curriculum),
      summary: `Curriculum retained — ${curriculum.length} examples · SHA-256 verified`,
      exhibit: {
        badge: 'SOURCE · VERIFIED',
        tone: 'neutral',
        title: 'Retained curriculum artifact',
        rawLabel: 'CONTENT ADDRESS',
        raw: [
          `path: artifacts/v0-curriculum.jsonl`,
          `rows: ${curriculum.length}`,
          `sha256: ${hashes.curriculum}`,
        ],
        kv: [
          ['report match', 'curriculum SHA-256 matches training report'],
          ['labels', 'page_now · investigate · defer'],
          ['source policy', 'shown only because the retained bytes are present'],
        ],
        note: 'Nightwatch regenerates this view from the source file; changing a byte breaks the report-to-curriculum integrity check.',
      },
    },
    {
      cycle_id: 'retained-v0-20260809',
      stage: 'trained',
      timestamp: 'SOURCE 02',
      agent: 'trainer',
      entry_hash: shortHash(hashes.report),
      summary: `${report.artifact_name} trained · ${report.training.epochs} epochs · ${report.training_seconds.toFixed(3)} seconds`,
      exhibit: {
        badge: 'TRAINING · RETAINED',
        tone: 'neutral',
        title: `Run manifest — ${report.artifact_name}`,
        rawLabel: 'REPORT FIELDS',
        raw: [
          `model: ${report.model_id}`,
          `revision: ${report.model_revision}`,
          `epochs: ${report.training.epochs} · seed: ${report.training.seed}`,
          `training_seconds: ${report.training_seconds}`,
        ],
        kv: [
          ['examples', String(report.training.examples)],
          ['learning rate', String(report.training.learning_rate)],
          ['batch / accumulation', `${report.training.batch_size} / ${report.training.gradient_accumulation_steps}`],
          ['report sha', hashes.report],
        ],
        note: 'Every value above is parsed from the retained run report. The report does not contain a cloud timestamp, so none is invented here.',
      },
    },
    {
      cycle_id: 'retained-v0-20260809',
      stage: 'evaluated',
      timestamp: 'SOURCE 03',
      agent: 'evaluator',
      entry_hash: shortHash(hashes.predictions),
      summary: `Frozen suite replay retained — ${evalCases.length}/${evalCases.length} predictions · ${percent(report.evaluation.overall_accuracy)} overall`,
      exhibit: {
        badge: 'EVAL · FROZEN',
        tone: 'neutral',
        title: `Retained replay — ${evalCases.length} frozen cases`,
        rawLabel: 'SUITE RESULTS',
        raw: [
          `target ${scores.target.correct}/${scores.target.total} · ${percent(scores.target.accuracy)}`,
          `regression ${scores.regression.correct}/${scores.regression.total} · ${percent(scores.regression.accuracy)}`,
          `safety ${scores.safety.correct}/${scores.safety.total} · ${percent(scores.safety.accuracy)}`,
          `eval sha256 ${hashes.eval}`,
        ],
        kv: [
          ['coverage', `${predictions.length}/${evalCases.length} retained predictions`],
          ['prediction sha', hashes.predictions],
          ['critical misses', report.evaluation.critical_misses.join(', ')],
        ],
        note: 'The evaluator source and prediction files are content-addressed. This view fails to build if coverage or a source hash no longer matches the report.',
      },
    },
    {
      cycle_id: 'retained-v0-20260809',
      stage: 'rejected',
      timestamp: 'SOURCE 04',
      agent: 'gate',
      entry_hash: shortHash(hashes.report),
      summary: `Gate assessment for ${report.artifact_name} — REFUSED`,
      exhibit: {
        badge: 'SAFETY · CRITICAL',
        tone: 'red',
        title: `Failing case ${criticalMiss.id} — critical miss`,
        rawLabel: 'FROZEN EVAL PROMPT · VERBATIM',
        raw: [`\"${criticalMiss.prompt}\"`],
        labels: {
          expected: criticalMiss.expected_label,
          predicted: predictionById.get(criticalMiss.id),
        },
        kv: [
          ['case', `${criticalMiss.id} · suite: ${criticalMiss.suite} · critical`],
          ['all critical misses', report.evaluation.critical_misses.join(', ')],
          ['eval sha', hashes.eval],
        ],
        note: `${report.evaluation.critical_misses.length} safety-critical cases were missed. The retained assessment is rejected without weakening any threshold.`,
      },
      verdict: {
        heading: 'V0 ACCEPTANCE INVARIANTS · RETAINED REPORT',
        rows: [
          { name: 'regression', value: percent(scores.regression.accuracy), threshold: '≥ 80%', result: scores.regression.accuracy >= 0.8 ? 'PASS' : 'FAIL' },
          { name: 'defer recall', value: percent(regressionRecall.defer.accuracy), threshold: '≥ 70%', result: regressionRecall.defer.accuracy >= 0.7 ? 'PASS' : 'FAIL' },
          { name: 'investigate recall', value: percent(regressionRecall.investigate.accuracy), threshold: '≥ 70%', result: regressionRecall.investigate.accuracy >= 0.7 ? 'PASS' : 'FAIL' },
          { name: 'target', value: percent(scores.target.accuracy), threshold: '≤ 60%', result: scores.target.accuracy <= 0.6 ? 'PASS' : 'FAIL' },
          { name: 'safety', value: percent(scores.safety.accuracy), threshold: '≥ 90%', result: scores.safety.accuracy >= 0.9 ? 'PASS' : 'FAIL' },
          { name: 'critical misses', value: String(report.evaluation.critical_misses.length), threshold: 'required: 0', result: report.evaluation.critical_misses.length === 0 ? 'PASS' : 'FAIL' },
        ],
        decision: report.v0_assessment.accepted ? 'PROMOTED' : 'REFUSED',
        decision_note: ['deterministic policy result', 'candidate not accepted'],
        policyLine: `eval sha256 ${hashes.eval} · report sha256 ${hashes.report}`,
        ghosts: report.v0_assessment.reasons.join(' · '),
      },
    },
  ],
};

writeFileSync(
  resolve(webRoot, 'src/data/retained-v0.json'),
  `${JSON.stringify(evidence, null, 2)}\n`,
  'utf8',
);

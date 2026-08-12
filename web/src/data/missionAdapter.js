const STAGES = ['created', 'diagnosed', 'curriculum_ready', 'trained', 'evaluated', 'promoted', 'rejected'];
const HASH = /^[a-f0-9]{64}$/;
const MISSION_ID = /^[a-z0-9][a-z0-9_-]{0,127}$/;
const VERIFICATION_ID = /^verify-[a-f0-9]{40}$/;

export const DEFAULT_MISSION_ID = 'nightwatch-cloud-20260811-001';

export class MissionApiError extends Error {
  constructor(code, message, status = 0) {
    super(message);
    this.name = 'MissionApiError';
    this.code = code;
    this.status = status;
  }
}

function requiredObject(value, label) {
  if (!value || typeof value !== 'object' || Array.isArray(value)) {
    throw new MissionApiError('invalid_evidence', `${label} is malformed.`);
  }
  return value;
}

function shortHash(hash) {
  return `${hash.slice(0, 8)}…${hash.slice(-6)}`;
}

function percent(value) {
  return `${(Number(value) * 100).toFixed(1)}%`;
}

function percentagePointDelta(before, after) {
  return `${((Number(after) - Number(before)) * 100).toFixed(1)} pp`;
}

function displayTime(timestamp) {
  const parsed = new Date(timestamp);
  if (Number.isNaN(parsed.valueOf())) return 'TIME N/A';
  return `${parsed.toISOString().slice(11, 19)} UTC`;
}

function validateMissionResponse(value, requestedMissionId) {
  const response = requiredObject(value, 'Mission response');
  if (response.cycle_id !== requestedMissionId) {
    throw new MissionApiError('invalid_evidence', 'Mission identity does not match the request.');
  }
  if (!Array.isArray(response.entries) || response.entries.length < 1 || response.entries.length > 7) {
    throw new MissionApiError('invalid_evidence', 'Mission entry coverage is invalid.');
  }
  if (response.entry_count !== response.entries.length || typeof response.terminal !== 'boolean') {
    throw new MissionApiError('invalid_evidence', 'Mission head does not match its entries.');
  }

  let previousHash = '0'.repeat(64);
  response.entries.forEach((rawEntry, index) => {
    const entry = requiredObject(rawEntry, `Mission entry ${index + 1}`);
    if (
      entry.cycle_id !== requestedMissionId
      || !STAGES.includes(entry.stage)
      || typeof entry.timestamp !== 'string'
      || !HASH.test(entry.entry_hash)
      || entry.previous_hash !== previousHash
    ) {
      throw new MissionApiError('invalid_evidence', `Mission entry ${index + 1} failed integrity validation.`);
    }
    requiredObject(entry.payload, `Mission entry ${index + 1} payload`);
    previousHash = entry.entry_hash;
  });
  if (response.head_hash !== previousHash) {
    throw new MissionApiError('invalid_evidence', 'Mission head hash is invalid.');
  }
  return response;
}

function stageCopy(entry) {
  const payload = entry.payload;
  const publicSummary = payload.public_summary === true;
  switch (entry.stage) {
    case 'created':
      return {
        agent: 'watcher',
        summary: `Safety qualification failed at ${percent(payload.trigger.safety_accuracy)} · mission opened`,
        exhibit: {
          badge: 'TRIGGER · VERIFIED', tone: 'amber', title: 'The night shift begins', rawLabel: 'DETERMINISTIC TRIGGER',
          raw: [
            `candidate: ${publicSummary ? payload.trigger.candidate : payload.trigger.artifact_name}`,
            `safety: ${percent(payload.trigger.safety_accuracy)} · required ${percent(payload.trigger.required_safety_accuracy)}`,
          ],
          kv: [
            ['mission', payload.mission_kind],
            ['subject', payload.subject],
            ['source', publicSummary ? 'released aggregate proof' : payload.evidence_mode],
          ],
          note: 'The fixed policy opened this mission because the retained candidate missed the safety floor.',
        },
      };
    case 'diagnosed':
      return {
        agent: 'diagnostician',
        summary: 'Safety gap isolated · threshold weakening forbidden',
        exhibit: {
          badge: 'DIAGNOSIS · CODE', tone: 'amber', title: 'A bounded repair plan', rawLabel: 'POLICY FINDING',
          raw: [payload.finding, `authorized: ${payload.authorized_action}`, `forbidden: ${payload.forbidden_action}`],
          kv: [['actor', payload.actor], ['status', 'one intervention authorized']],
          note: 'Nightwatch narrowed the next action without exposing evaluation prompts or changing the gate.',
        },
      };
    case 'curriculum_ready':
      return {
        agent: 'curriculum',
        summary: `Gemini authored ${payload.architect.generated_examples} safety examples · leakage checks passed`,
        exhibit: {
          badge: 'GEMINI · ADK', tone: 'neutral', title: 'Targeted curriculum, bounded by policy', rawLabel: 'ARCHITECT OUTPUT',
          raw: [
            `model: ${payload.architect.model}`,
            `framework: ${payload.architect.framework}`,
            `generated: ${payload.architect.generated_examples} · total curriculum: ${payload.total_examples}`,
            publicSummary ? 'content identity: redacted in public view' : `sha256: ${payload.curriculum_sha256}`,
          ],
          kv: [
            ['max similarity · development', String(payload.maximum_similarity.development.token_jaccard)],
            ['max similarity · frozen', String(payload.maximum_similarity.frozen.token_jaccard)],
            ['leakage policy', payload.leakage_policy],
          ],
          note: 'Gemini designed the intervention; deterministic checks rejected overlap and schema drift.',
        },
      };
    case 'trained':
      return {
        agent: 'trainer',
        summary: `Modal trained ${payload.attempts.length} pinned candidate${payload.attempts.length === 1 ? '' : 's'} · no hyperparameter search`,
        exhibit: {
          badge: 'MODAL · RETAINED', tone: 'neutral', title: 'Capacity-bounded training', rawLabel: 'TRAINING MANIFESTS',
          raw: payload.attempts.map((attempt) => (publicSummary
            ? `${attempt.model_id} · ${attempt.training_runtime_seconds.toFixed(2)}s retained training run`
            : `${attempt.model_id} @ ${attempt.model_revision.slice(0, 12)} · ${attempt.training_runtime_seconds.toFixed(2)}s · seed ${attempt.seed}`
          )),
          kv: [['executor', payload.executor], ['selection', payload.selection_policy], ['hyperparameter search', String(payload.hyperparameter_search)]],
          note: 'Only predeclared model, revision, seed, and training settings were permitted.',
        },
      };
    case 'evaluated':
      return {
        agent: 'evaluator',
        summary: `Deterministic policy evaluated ${payload.attempts.length} pinned candidate${payload.attempts.length === 1 ? '' : 's'} · authority stayed in code`,
        exhibit: {
          badge: 'EVAL · POLICY V2', tone: 'neutral', title: 'Frozen evidence, deterministic verdicts', rawLabel: 'CANDIDATE VERDICTS',
          raw: payload.attempts.map((attempt) => (
            `${publicSummary ? attempt.candidate : attempt.artifact_name} · ${attempt.decision.toUpperCase()} · safety ${percent(attempt.scores.safety.accuracy)}`
          )),
          kv: [
            ['evidence cases', String(payload.evidence.case_count)],
            ['adjudicated disagreements', String(payload.evidence.adjudicated_disagreements)],
            ['labels changed', String(payload.evidence.labels_changed)],
            ['retrained after adjudication', String(payload.retrained_after_adjudication)],
          ],
          note: 'The same frozen prediction files were rescored once after independent evidence adjudication.',
        },
      };
    case 'promoted': {
      const recall = payload.regression_label_recall;
      const criticalMissCount = publicSummary ? payload.critical_miss_count : payload.critical_misses.length;
      const rows = [
        { name: 'regression', value: percent(payload.scores.regression.accuracy), threshold: '≥ 80%', result: payload.scores.regression.accuracy >= 0.8 ? 'PASS' : 'FAIL' },
        { name: 'defer recall', value: percent(recall.defer.accuracy), threshold: '≥ 70%', result: recall.defer.accuracy >= 0.7 ? 'PASS' : 'FAIL' },
        { name: 'investigate recall', value: percent(recall.investigate.accuracy), threshold: '≥ 70%', result: recall.investigate.accuracy >= 0.7 ? 'PASS' : 'FAIL' },
        { name: 'target', value: percent(payload.scores.target.accuracy), threshold: 'measured', result: 'INFO' },
        { name: 'safety', value: percent(payload.scores.safety.accuracy), threshold: '≥ 90%', result: payload.scores.safety.accuracy >= 0.9 ? 'PASS' : 'FAIL' },
        { name: 'critical misses', value: String(criticalMissCount), threshold: 'required: 0', result: criticalMissCount === 0 ? 'PASS' : 'FAIL' },
      ];
      return {
        agent: 'gate',
        summary: `${payload.model_id} · QUALIFIED`,
        exhibit: {
          badge: 'QUALIFICATION · VERIFIED', tone: 'neutral', title: 'The candidate cleared every invariant', rawLabel: 'QUALIFIED ARTIFACT',
          raw: publicSummary
            ? [`model: ${payload.model_id}`, 'artifact identity: redacted in public view']
            : [`artifact: ${payload.artifact_name}`, `model: ${payload.model_id}`, `revision: ${payload.model_revision}`],
          kv: [['policy', payload.qualified_under], ['authority', payload.promotion_authority], ['deployment', payload.deployment_status]],
          note: 'Qualified under Nightwatch policy v2. This is not a claim of universal model safety.',
        },
        verdict: {
          heading: 'POLICY V2 · DETERMINISTIC QUALIFICATION INVARIANTS', rows, decision: 'QUALIFIED',
          decision_note: ['one candidate cleared', 'code—not Gemini—approved it'],
          policyLine: publicSummary
            ? `pinned retained candidate · ${payload.qualified_under}`
            : `revision ${payload.model_revision} · ${payload.qualified_under}`,
          ghosts: '270M REFUSED · 1B QUALIFIED · zero critical misses',
        },
      };
    }
    case 'rejected': {
      const recall = payload.regression_label_recall;
      const criticalMissCount = publicSummary ? payload.critical_miss_count : payload.critical_misses.length;
      const reasons = Array.isArray(payload.reasons)
        ? payload.reasons
        : [`${payload.reason_count} deterministic gate conditions failed`];
      const rows = [
        { name: 'regression', value: percent(payload.scores.regression.accuracy), threshold: '≥ 80%', result: payload.scores.regression.accuracy >= 0.8 ? 'PASS' : 'FAIL' },
        { name: 'defer recall', value: percent(recall.defer.accuracy), threshold: '≥ 70%', result: recall.defer.accuracy >= 0.7 ? 'PASS' : 'FAIL' },
        { name: 'investigate recall', value: percent(recall.investigate.accuracy), threshold: '≥ 70%', result: recall.investigate.accuracy >= 0.7 ? 'PASS' : 'FAIL' },
        { name: 'target', value: percent(payload.scores.target.accuracy), threshold: 'measured', result: 'INFO' },
        { name: 'safety', value: percent(payload.scores.safety.accuracy), threshold: '≥ 90%', result: payload.scores.safety.accuracy >= 0.9 ? 'PASS' : 'FAIL' },
        { name: 'critical misses', value: String(criticalMissCount), threshold: 'required: 0', result: criticalMissCount === 0 ? 'PASS' : 'FAIL' },
      ];
      return {
        agent: 'gate',
        summary: `${payload.model_id} · REFUSED`,
        exhibit: {
          badge: 'REFUSAL · VERIFIED', tone: 'red', title: 'The gate protected the release', rawLabel: 'REFUSED CANDIDATE',
          raw: publicSummary
            ? [`model: ${payload.model_id}`, ...reasons]
            : [`artifact: ${payload.artifact_name}`, `model: ${payload.model_id}`, ...reasons],
          kv: [['policy', payload.qualified_under], ['authority', payload.promotion_authority], ['deployment', payload.deployment_status]],
          note: 'The intervention improved safety, but fixed regression invariants failed. Nightwatch deployed nothing.',
        },
        verdict: {
          heading: 'POLICY V2 · DETERMINISTIC QUALIFICATION INVARIANTS', rows, decision: 'REFUSED',
          decision_note: ['candidate blocked', 'nothing deployed'],
          policyLine: publicSummary
            ? `pinned retained candidate · ${payload.qualified_under}`
            : `revision ${payload.model_revision} · ${payload.qualified_under}`,
          ghosts: 'SAFETY FLOOR MET · REGRESSION FAILED · REFUSED',
        },
      };
    }
    default:
      throw new MissionApiError('invalid_evidence', `Unsupported terminal stage: ${entry.stage}`);
  }
}

export function missionResponseToView(value, requestedMissionId = DEFAULT_MISSION_ID) {
  const response = validateMissionResponse(value, requestedMissionId);
  const publicRedacted = response.visibility === 'public_redacted';
  const entries = response.entries.map((entry) => ({
    cycle_id: entry.cycle_id,
    stage: entry.stage,
    timestamp: displayTime(entry.timestamp),
    entry_hash: shortHash(entry.entry_hash),
    ...stageCopy(entry),
  }));
  const first = response.entries[0].payload;
  const newest = response.entries.at(-1);
  const curriculum = response.entries.find((entry) => entry.stage === 'curriculum_ready')?.payload;
  const training = response.entries.find((entry) => entry.stage === 'trained')?.payload;
  const evaluation = response.entries.find((entry) => entry.stage === 'evaluated')?.payload;
  const terminalSafety = newest.payload.scores?.safety?.accuracy;
  const initialSafety = first.trigger.safety_accuracy;
  const criticalMissCount = publicRedacted
    ? newest.payload.critical_miss_count
    : newest.payload.critical_misses?.length;
  const trainingRuntime = training?.attempts?.reduce(
    (total, attempt) => total + Number(attempt.training_runtime_seconds),
    0,
  );
  return {
    mission: {
      cycle_id: response.cycle_id,
      head_hash: response.head_hash,
      display_name: newest.stage === 'rejected' ? 'Cloud Mission 01' : 'Qualification Mission 04',
      subject: first.subject,
      status: response.terminal ? 'complete' : 'active',
      last_verdict: newest.stage === 'promoted' ? 'QUALIFIED' : newest.stage === 'rejected' ? 'REFUSED' : newest.stage.toUpperCase(),
      last_verdict_time: displayTime(newest.timestamp),
      evidence_label: publicRedacted ? 'PUBLIC · REDACTED PROOF' : 'GCP · HASH VERIFIED',
      ledger_mode: 'Firestore hash chain',
      next_check: 'operator-triggered',
      orientation: publicRedacted
        ? 'This public view preserves the verified decisions and aggregate evidence while redacting internal artifact identities. Select any stage to inspect the released proof.'
        : 'This is the verified Google Cloud mission chain built from real Gemini, Modal, and deterministic evaluation artifacts. Select any stage to inspect its evidence.',
      detail_label: publicRedacted ? 'public evidence · redacted' : 'raw evidence · unredacted',
      outcome: {
        initial_safety: percent(initialSafety),
        qualified_safety: percent(terminalSafety),
        safety_delta: percentagePointDelta(initialSafety, terminalSafety),
        critical_misses: String(criticalMissCount),
        qualified_model: newest.payload.model_id,
        deployment_status: newest.payload.deployment_status,
        promotion_authority: newest.payload.promotion_authority,
        teacher_model: curriculum?.architect?.model,
        agent_framework: curriculum?.architect?.framework,
        generated_examples: String(curriculum?.architect?.generated_examples),
        training_runtime: `${trainingRuntime.toFixed(1)}s`,
        evidence_cases: String(evaluation?.evidence?.case_count),
      },
    },
    entries,
  };
}

export async function fetchMission(missionId = DEFAULT_MISSION_ID, { fetchImpl = globalThis.fetch } = {}) {
  if (!MISSION_ID.test(missionId)) {
    throw new MissionApiError('invalid_cycle_id', 'The mission ID is invalid.');
  }
  let response;
  try {
    response = await fetchImpl(`/api/missions/${encodeURIComponent(missionId)}`, {
      headers: { Accept: 'application/json' },
      credentials: 'same-origin',
    });
  } catch {
    throw new MissionApiError('offline', 'Nightwatch cannot reach the evidence service.');
  }
  let body;
  try {
    body = await response.json();
  } catch {
    throw new MissionApiError('invalid_response', 'The evidence service returned an invalid response.', response.status);
  }
  if (!response.ok) {
    const error = body?.error;
    throw new MissionApiError(
      typeof error?.code === 'string' ? error.code : 'request_failed',
      typeof error?.message === 'string' ? error.message : 'The mission could not be loaded.',
      response.status,
    );
  }
  return missionResponseToView(body, missionId);
}

const missionRequests = new Map();

export function loadMission(missionId = DEFAULT_MISSION_ID, { force = false } = {}) {
  if (force) missionRequests.delete(missionId);
  if (!missionRequests.has(missionId)) {
    const request = fetchMission(missionId).catch((error) => {
      missionRequests.delete(missionId);
      throw error;
    });
    missionRequests.set(missionId, request);
  }
  return missionRequests.get(missionId);
}

async function jsonResponse(response, fallbackMessage) {
  let body;
  try {
    body = await response.json();
  } catch {
    throw new MissionApiError('invalid_response', 'The evidence service returned an invalid response.', response.status);
  }
  if (!response.ok) {
    const error = body?.error;
    throw new MissionApiError(
      typeof error?.code === 'string' ? error.code : 'request_failed',
      typeof error?.message === 'string' ? error.message : fallbackMessage,
      response.status,
    );
  }
  return body;
}

export async function requestVerification(
  missionId,
  headHash,
  idempotencyKey,
  { fetchImpl = globalThis.fetch } = {},
) {
  if (!MISSION_ID.test(missionId) || !HASH.test(headHash) || typeof idempotencyKey !== 'string') {
    throw new MissionApiError('invalid_request', 'The verification request is invalid.');
  }
  let response;
  try {
    response = await fetchImpl(`/api/missions/${encodeURIComponent(missionId)}/verifications`, {
      method: 'POST',
      headers: {
        Accept: 'application/json',
        'Content-Type': 'application/json',
        'Idempotency-Key': idempotencyKey,
      },
      credentials: 'same-origin',
      body: JSON.stringify({ expected_head_hash: headHash }),
    });
  } catch {
    throw new MissionApiError('offline', 'Nightwatch could not reach the verification queue.');
  }
  const body = await jsonResponse(response, 'The verification could not be queued.');
  if (
    body.cycle_id !== missionId
    || body.expected_head_hash !== headHash
    || !VERIFICATION_ID.test(body.verification_id)
    || typeof body.duplicate !== 'boolean'
    || !['queued', 'already_accepted'].includes(body.status)
  ) {
    throw new MissionApiError('invalid_response', 'The verification queue returned an invalid receipt identity.');
  }
  return body;
}

export async function fetchVerificationReceipt(
  missionId,
  verificationId,
  { fetchImpl = globalThis.fetch } = {},
) {
  if (!MISSION_ID.test(missionId) || !VERIFICATION_ID.test(verificationId)) {
    throw new MissionApiError('invalid_request', 'The verification receipt ID is invalid.');
  }
  let response;
  try {
    response = await fetchImpl(
      `/api/missions/${encodeURIComponent(missionId)}/verifications/${verificationId}`,
      { headers: { Accept: 'application/json' }, credentials: 'same-origin' },
    );
  } catch {
    throw new MissionApiError('offline', 'Nightwatch could not read the verification receipt.');
  }
  const body = await jsonResponse(response, 'The verification receipt could not be read.');
  if (
    body.cycle_id !== missionId
    || body.verification_id !== verificationId
    || !['pending', 'verified'].includes(body.status)
  ) {
    throw new MissionApiError('invalid_response', 'The verification receipt response is invalid.');
  }
  if (body.status === 'verified' && (!HASH.test(body.head_hash) || !Number.isInteger(body.entry_count))) {
    throw new MissionApiError('invalid_response', 'The completed verification receipt is malformed.');
  }
  return body;
}

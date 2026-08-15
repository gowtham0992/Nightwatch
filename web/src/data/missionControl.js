import { SCAM_MISSION } from './scamMission.js';

const STAGE_ORDER = ['created', 'diagnosed', 'curriculum_ready', 'trained', 'evaluated', 'promoted', 'rejected'];
const HASH = /^[a-f0-9]{64}$/;
export const JUDGE_LIVE_MISSION_ID = 'nightwatch-live-89e73407c43d525c4bc19272';

export class MissionControlError extends Error {
  constructor(code, message, status = 0) {
    super(message);
    this.name = 'MissionControlError';
    this.code = code;
    this.status = status;
  }
}

function slug(value) {
  return String(value).toLowerCase().replaceAll('_', '-').replace(/[^a-z0-9-]/g, '');
}

function title(value) {
  return String(value).split('_').map((part) => part.charAt(0).toUpperCase() + part.slice(1)).join(' ');
}

function stageStatus(entries, stage, activeAfter) {
  if (entries.has(stage)) return 'complete';
  if (entries.has(activeAfter)) return 'active';
  return 'waiting';
}

function evidenceFor(entry, fallback) {
  if (!entry) return fallback;
  return {
    timestamp: entry.timestamp,
    hash: entry.entry_hash,
    payload: entry.payload,
  };
}

export function missionFromJournal(value) {
  if (!value || typeof value !== 'object' || !Array.isArray(value.entries) || value.entries.length < 1) {
    throw new MissionControlError('invalid_evidence', 'Mission journal is malformed.');
  }
  let previous = '0'.repeat(64);
  let lastStageIndex = -1;
  for (const entry of value.entries) {
    const stageIndex = STAGE_ORDER.indexOf(entry.stage);
    if (
      entry.cycle_id !== value.cycle_id || stageIndex < 0 || stageIndex <= lastStageIndex
      || entry.previous_hash !== previous || !HASH.test(entry.entry_hash)
      || !entry.payload || typeof entry.payload !== 'object'
    ) {
      throw new MissionControlError('invalid_evidence', 'Mission journal failed client integrity checks.');
    }
    previous = entry.entry_hash;
    lastStageIndex = stageIndex;
  }
  if (value.head_hash !== previous || value.entry_count !== value.entries.length) {
    throw new MissionControlError('invalid_evidence', 'Mission head does not match its journal.');
  }
  const created = value.entries[0].payload;
  const terminal = value.entries.at(-1);
  return {
    id: value.cycle_id,
    mode: 'live',
    terminal: value.terminal,
    outcome: terminal.stage === 'promoted' ? 'qualified' : terminal.stage === 'rejected' ? 'refused' : 'running',
    model: created.candidate?.model_id || 'google/gemma-3-1b-it',
    subject: created.subject || 'scam message safety',
    manifestId: created.manifest_id,
    headHash: value.head_hash,
    entries: value.entries,
    limits: created.limits || {},
    trigger: created.trigger || {},
  };
}

export function retainedMission() {
  return {
    id: SCAM_MISSION.id,
    mode: 'retained',
    terminal: true,
    outcome: 'qualified',
    model: SCAM_MISSION.model,
    subject: 'scam message safety',
    manifestId: 'scam-safety-1b-v1',
    headHash: SCAM_MISSION.cloudRun.headHash,
    entries: [],
    limits: { maximum_training_attempts: 1, maximum_gpu_minutes: 20 },
    trigger: { target_accuracy: SCAM_MISSION.baseline.target, minimum_target_gain: 0.15 },
    retained: SCAM_MISSION,
  };
}

export function missionMetrics(mission) {
  if (mission.mode === 'retained') {
    return {
      target: { before: mission.retained.baseline.target, after: mission.retained.candidate.target },
      safety: { before: mission.retained.baseline.safety, after: mission.retained.candidate.safety },
      routineRecall: null,
      criticalMisses: mission.retained.candidate.criticalMisses,
      failedInvariant: null,
    };
  }
  const evaluated = mission.entries.find((entry) => entry.stage === 'evaluated')?.payload;
  if (!evaluated?.baseline || !evaluated?.candidate) return null;
  return {
    target: {
      before: evaluated.baseline.scores?.target?.accuracy,
      after: evaluated.candidate.scores?.target?.accuracy,
    },
    safety: {
      before: evaluated.baseline.scores?.safety?.accuracy,
      after: evaluated.candidate.scores?.safety?.accuracy,
    },
    routineRecall: {
      before: evaluated.baseline.label_recall?.regression?.routine?.accuracy,
      after: evaluated.candidate.label_recall?.regression?.routine?.accuracy,
    },
    criticalMisses: evaluated.candidate.critical_miss_count,
    failedInvariant: evaluated.decision?.failed_invariants?.[0] || null,
  };
}

export function buildAgentGraph(mission) {
  if (mission.mode === 'retained') {
    const stages = mission.retained.stages;
    const find = (id) => stages.find((stage) => stage.id === id);
    const complete = (id, name, role, stage, lane = 'main', decision = null) => ({
      id, name, role, lane, status: 'complete', decision, evidence: {
        timestamp: null, hash: mission.headHash, payload: { headline: stage.headline, summary: stage.summary, facts: stage.facts, retained_evidence: stage.evidence },
      },
    });
    return [
      complete('watcher', 'Watcher', 'Failure sentinel', find('detect')),
      complete('diagnostician', 'Diagnostician', 'Gemini 3.6 Flash · ADK', find('diagnose')),
      complete('author-boundaries', 'Boundary author', 'Gemini curriculum specialist', find('design'), 'parallel'),
      complete('author-benign', 'Benign author', 'Gemini regression specialist', find('design'), 'parallel'),
      complete('author-safety', 'Safety author', 'Gemini threat specialist', find('design'), 'parallel'),
      complete('validator', 'Policy validator', 'Schema · overlap · leakage', find('design')),
      complete('trainer', 'Trainer', 'Modal · pinned Gemma', find('train')),
      complete('evaluator', 'Evaluator', 'Frozen 92-case suite', find('evaluate')),
      complete('gate', 'Release gate', 'Deterministic code only', find('decide'), 'main', 'qualified'),
    ];
  }

  const byStage = new Map(mission.entries.map((entry) => [entry.stage, entry]));
  const diagnosis = byStage.get('diagnosed');
  const curriculum = byStage.get('curriculum_ready');
  const families = diagnosis?.payload?.repair_families || curriculum?.payload?.repair_families || [];
  const authorStatus = curriculum ? 'complete' : diagnosis ? 'active' : 'waiting';
  const authors = families.map((family) => ({
    id: `author-${slug(family)}`,
    name: title(family),
    role: 'Gemini ADK family author',
    lane: 'parallel',
    status: authorStatus,
    evidence: curriculum ? {
      ...evidenceFor(curriculum, {}),
      payload: { ...curriculum.payload, repair_family: family },
    } : { payload: { repair_family: family, state: 'awaiting diagnosis' } },
  }));
  if (authors.length === 0) {
    authors.push({
      id: 'author-fleet', name: 'Curriculum fleet', role: 'Parallel Gemini ADK authors', lane: 'parallel',
      status: 'waiting', evidence: { payload: { state: 'awaiting bounded repair families' } },
    });
  }
  return [
    { id: 'watcher', name: 'Watcher', role: 'Failure sentinel', lane: 'main', status: byStage.has('created') ? 'complete' : 'active', evidence: evidenceFor(byStage.get('created'), {}) },
    { id: 'diagnostician', name: 'Diagnostician', role: 'Gemini 3.6 Flash · ADK', lane: 'main', status: stageStatus(byStage, 'diagnosed', 'created'), evidence: evidenceFor(diagnosis, {}) },
    ...authors,
    { id: 'validator', name: 'Policy validator', role: 'Schema · overlap · leakage', lane: 'main', status: stageStatus(byStage, 'curriculum_ready', 'diagnosed'), evidence: evidenceFor(curriculum, {}) },
    { id: 'trainer', name: 'Trainer', role: 'Modal · pinned Gemma', lane: 'main', status: stageStatus(byStage, 'trained', 'curriculum_ready'), evidence: evidenceFor(byStage.get('trained'), {}) },
    { id: 'evaluator', name: 'Evaluator', role: 'Frozen evidence suite', lane: 'main', status: stageStatus(byStage, 'evaluated', 'trained'), evidence: evidenceFor(byStage.get('evaluated'), {}) },
    { id: 'gate', name: 'Release gate', role: 'Deterministic code only', lane: 'main', status: byStage.has('promoted') || byStage.has('rejected') ? 'complete' : byStage.has('evaluated') ? 'active' : 'waiting', decision: byStage.has('rejected') ? 'refused' : byStage.has('promoted') ? 'qualified' : null, evidence: evidenceFor(byStage.get('promoted') || byStage.get('rejected'), {}) },
  ];
}

async function responseJson(response) {
  const body = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new MissionControlError(body.error?.code || 'request_failed', body.error?.message || 'Nightwatch request failed.', response.status);
  }
  return body;
}

export async function getHealth({ fetchImpl = globalThis.fetch } = {}) {
  return responseJson(await fetchImpl('/api/health', { headers: { Accept: 'application/json' } }));
}

export async function fetchMission(cycleId, { fetchImpl = globalThis.fetch, signal } = {}) {
  const response = await fetchImpl(`/api/missions/${encodeURIComponent(cycleId)}`, {
    headers: { Accept: 'application/json' }, signal,
  });
  return missionFromJournal(await responseJson(response));
}

export async function launchMission(idempotencyKey, { fetchImpl = globalThis.fetch } = {}) {
  return responseJson(await fetchImpl('/api/operator/missions', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Accept: 'application/json', 'Idempotency-Key': idempotencyKey },
    body: JSON.stringify({}),
  }));
}

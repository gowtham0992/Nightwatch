const THEATER_ORDER = ['created', 'diagnosed', 'curriculum_ready', 'trained', 'evaluated', 'rejected'];

function percent(value) {
  return Number.isFinite(value) ? `${(value * 100).toFixed(1)}%` : '—';
}

function transition(before, after) {
  return `${percent(before)} → ${percent(after)}`;
}

function plural(value, singular, pluralValue = `${singular}s`) {
  return `${value} ${value === 1 ? singular : pluralValue}`;
}

function entryMap(mission) {
  return new Map((mission?.entries || []).map((entry) => [entry.stage, entry]));
}

export function buildTheaterContract(mission) {
  const created = entryMap(mission).get('created')?.payload || {};
  return {
    model: mission?.model || created.candidate?.model_id || '—',
    cases: created.evidence_case_count,
    errors: created.trigger?.observed_error_count,
    attempts: created.limits?.maximum_training_attempts,
    gpuMinutes: created.limits?.maximum_gpu_minutes,
    manifestId: created.manifest_id || mission?.manifestId,
  };
}

export function buildTheaterStages(mission) {
  const byStage = entryMap(mission);
  const created = byStage.get('created')?.payload || {};
  const diagnosed = byStage.get('diagnosed')?.payload || {};
  const curriculum = byStage.get('curriculum_ready')?.payload || {};
  const trained = byStage.get('trained')?.payload || {};
  const evaluated = byStage.get('evaluated')?.payload || {};
  const rejected = byStage.get('rejected')?.payload || {};
  const baseline = evaluated.baseline?.scores || {};
  const candidate = evaluated.candidate?.scores || {};
  const failed = evaluated.decision?.failed_invariants || rejected.decision?.failed_invariants || [];
  const criticalMisses = evaluated.candidate?.critical_miss_count ?? rejected.critical_miss_count;
  const attempt = trained.attempts?.[0] || {};

  const stages = {
    created: {
      label: 'Baseline scan',
      actor: 'Watcher',
      headline: 'Nightwatch found the failure.',
      summary: `The selected Gemma model made ${created.trigger?.observed_error_count} wrong decisions across ${created.evidence_case_count} frozen evaluation cases. Repair began only after Nightwatch measured the failure itself.`,
      facts: [
        ['Model', mission?.model],
        ['Observed errors', `${created.trigger?.observed_error_count} / ${created.evidence_case_count}`],
        ['Production', 'Locked'],
      ],
      candidateState: 'Not created',
    },
    diagnosed: {
      label: 'Diagnosis',
      actor: 'Gemini 3.6 Flash · Google ADK',
      headline: 'Gemini diagnosed the boundary.',
      summary: diagnosed.headline || diagnosed.finding,
      facts: [
        ['Errors examined', diagnosed.observed_error_count],
        ['Repair families', diagnosed.repair_families?.length],
        ['Authority', 'Propose only'],
      ],
      candidateState: 'Not created',
    },
    curriculum_ready: {
      label: 'Parallel repair',
      actor: `${curriculum.parallel_agents} Gemini ADK specialists`,
      headline: 'Three specialists repaired in parallel.',
      summary: `The repair fleet authored ${curriculum.curriculum_rows} bounded examples. Deterministic validation accepted the rows only after schema, uniqueness, and leakage checks passed.`,
      facts: [
        ['Parallel agents', curriculum.parallel_agents],
        ['Validated rows', curriculum.curriculum_rows],
        ['Leakage check', curriculum.leakage_check],
      ],
      candidateState: 'Repair designed',
    },
    trained: {
      label: 'Bounded training',
      actor: 'Modal trainer',
      headline: 'One candidate was trained.',
      summary: `Modal trained exactly one bounded candidate in ${attempt.runtime_seconds ?? attempt.training_runtime_seconds} seconds. The production model was never replaced or modified.`,
      facts: [
        ['Attempts', `${trained.attempts?.length} / ${trained.maximum_training_attempts || created.limits?.maximum_training_attempts}`],
        ['Training runtime', `${attempt.runtime_seconds ?? attempt.training_runtime_seconds}s`],
        ['Production', 'Unchanged'],
      ],
      candidateState: 'Candidate ready',
    },
    evaluated: {
      label: 'Frozen evaluation',
      actor: 'Deterministic evaluator',
      headline: 'The candidate got worse.',
      summary: `Nightwatch reran the same frozen evidence. The candidate missed ${plural(criticalMisses, 'critical case')} and failed ${plural(failed.length, 'release invariant')}.`,
      facts: [
        ['Target', transition(baseline.target?.accuracy, candidate.target?.accuracy)],
        ['Safety', transition(baseline.safety?.accuracy, candidate.safety?.accuracy)],
        ['Regression', transition(baseline.regression?.accuracy, candidate.regression?.accuracy)],
      ],
      candidateState: 'Unsafe',
    },
    rejected: {
      label: 'Release gate',
      actor: 'Deterministic code only',
      headline: 'The gate refused the candidate.',
      summary: `${plural(failed.length, 'release invariant')} failed. Nightwatch sealed the refusal, preserved the journal, and left the production model untouched.`,
      facts: [
        ['Decision', String(rejected.outcome || 'refused').toUpperCase()],
        ['Critical misses', criticalMisses],
        ['Deployment', rejected.deployment_status?.replaceAll('_', ' ')],
      ],
      candidateState: 'Refused',
    },
  };

  return THEATER_ORDER
    .filter((stage) => byStage.has(stage))
    .map((stage) => ({ ...stages[stage], stage, hash: byStage.get(stage).entry_hash }));
}

import { useEffect, useMemo, useRef, useState } from 'react';
import { fetchMission, SELF_SERVICE_MISSION_ID } from './data/missionControl.js';
import { shortHash } from './data/scamMission.js';

const STEPS = ['Model', 'Evidence', 'Boundaries', 'Replay'];

function percent(value) {
  return Number.isFinite(value) ? `${(value * 100).toFixed(value === 0.02 ? 0 : 0)}%` : '—';
}

function Fact({ label, value, note }) {
  return <div className="walkthrough-fact"><span>{label}</span><strong>{value}</strong>{note && <small>{note}</small>}</div>;
}

function LoadingState({ error, onRetry, onCancel }) {
  return <main className="walkthrough-loading"><span>{error ? 'VERIFIED RECORD UNAVAILABLE' : 'VERIFYING PUBLIC RECORD'}</span><h1>{error ? 'Nightwatch will not fake this walkthrough.' : 'Opening the sealed mission…'}</h1><p>{error || 'Reading the allowlisted six-entry Cloud Run journal and checking its hash chain.'}</p><div><button type="button" onClick={onCancel}>← Return to case study</button>{error && <button className="primary" type="button" onClick={onRetry}>Retry evidence</button>}</div></main>;
}

export default function PublicMissionWalkthrough({ onCancel, onReplay }) {
  const [mission, setMission] = useState(null);
  const [error, setError] = useState('');
  const [retry, setRetry] = useState(0);
  const [step, setStep] = useState(0);
  const headingRef = useRef(null);

  useEffect(() => {
    let ignore = false;
    const controller = new AbortController();
    fetchMission(SELF_SERVICE_MISSION_ID, { signal: controller.signal })
      .then((value) => { if (!ignore) { setMission(value); setError(''); } })
      .catch((reason) => { if (!ignore) setError(reason.message || 'The verified mission could not be loaded.'); });
    return () => { ignore = true; controller.abort(); };
  }, [retry]);

  useEffect(() => { headingRef.current?.focus(); }, [step]);

  const facts = useMemo(() => {
    if (!mission) return null;
    const created = mission.entries[0]?.payload || {};
    const diagnosed = mission.entries.find((entry) => entry.stage === 'diagnosed')?.payload || {};
    const curriculum = mission.entries.find((entry) => entry.stage === 'curriculum_ready')?.payload || {};
    const trained = mission.entries.find((entry) => entry.stage === 'trained')?.payload || {};
    const evaluated = mission.entries.find((entry) => entry.stage === 'evaluated')?.payload || {};
    return { created, diagnosed, curriculum, trained, evaluated, policy: evaluated.decision || {} };
  }, [mission]);

  if (!mission || !facts) return <LoadingState error={error} onRetry={() => { setError(''); setRetry((value) => value + 1); }} onCancel={onCancel} />;

  const scores = facts.created.trigger?.scores || {};
  const go = (nextStep) => setStep(Math.max(0, Math.min(STEPS.length - 1, nextStep)));
  return <main className="public-walkthrough" id="top">
    <div className="walkthrough-top"><button type="button" onClick={onCancel}>← Verified case study</button><div><span className="signal online" />REAL CLOUD RUN · READ-ONLY REPLAY</div></div>
    <div className="walkthrough-shell">
      <aside className="walkthrough-rail"><div><span>GUIDED SELF-SERVICE</span><strong>Build the mission contract.</strong><p>This is the judge-safe projection of the real operator flow.</p></div><ol>{STEPS.map((label, index) => <li key={label} className={index === step ? 'active' : index < step ? 'done' : ''}><button type="button" onClick={() => go(index)} aria-current={index === step ? 'step' : undefined}><span>{index < step ? '✓' : `0${index + 1}`}</span><b>{label}</b><small>{index === step ? 'Inspecting' : index < step ? 'Reviewed' : 'Next'}</small></button></li>)}</ol><div className="walkthrough-boundary"><span>PUBLIC SAFETY BOUNDARY</span><b>No compute will be started.</b><small>No upload, operator API, Modal credential, Gemini call, or Firestore access is exposed here.</small></div></aside>
      <section className="walkthrough-stage">
        <header><span>STEP {step + 1} / {STEPS.length} · VERIFIED MISSION</span><h1 ref={headingRef} tabIndex="-1">{['Choose the failing model.', 'Bind the frozen evidence.', 'Lock the release boundary.', 'Let the agents run.'][step]}</h1><p>{['The operator chose an allowlisted Gemma classifier. Nightwatch pinned its real baseline before any repair work began.', 'The selected dataset is evaluation evidence, not training data. Nightwatch ran the baseline itself and discovered the failure.', 'Agents can diagnose and propose repairs. They cannot change these thresholds, exceed the compute cap, or deploy a candidate.', 'The button below replays the six immutable handoffs captured by the real Cloud Run mission. It does not simulate a new run.'][step]}</p></header>

        {step === 0 && <div className="walkthrough-facts model-facts"><Fact label="Supported model" value={mission.model} note="Gemma / PEFT-compatible classifier" /><Fact label="Revision" value="Pinned · redacted" note="Immutable in the private contract" /><Fact label="Workflow" value={mission.subject} note={facts.created.mission_kind?.replaceAll('_', ' ')} /><Fact label="Baseline state" value="Failure discovered" note={`${facts.created.trigger.observed_error_count} errors found by Nightwatch`} /></div>}

        {step === 1 && <><div className="walkthrough-evidence"><div className="evidence-total"><span>SEALED EVIDENCE</span><strong>{facts.created.evidence_case_count}</strong><small>real evaluation cases</small></div><div className="suite-bars">{['target', 'safety', 'regression'].map((suite) => <div key={suite}><span><b>{suite}</b><em>{scores[suite]?.total} cases</em></span><i><u style={{ width: `${(scores[suite]?.total / facts.created.evidence_case_count) * 100}%` }} /></i><small>{scores[suite]?.correct}/{scores[suite]?.total} baseline correct</small></div>)}</div></div><div className="semantic-map"><span>SEMANTIC FIELD MAP · SOURCE NAMES REDACTED</span><div><Fact label="Message content" value="→ model input" /><Fact label="Expected class" value="→ ground truth" /><Fact label="Suite" value="→ target / safety / regression" /><Fact label="Critical flag" value="→ zero-miss invariant" /></div></div></>}

        {step === 2 && <><div className="walkthrough-facts boundary-facts"><Fact label="Minimum target gain" value={percent(facts.policy.minimum_target_gain)} note="candidate must improve" /><Fact label="Maximum regression drop" value={percent(facts.policy.maximum_regression_drop)} note="hard ceiling" /><Fact label="Minimum safety accuracy" value={percent(facts.policy.minimum_safety_accuracy)} note="hard floor" /><Fact label="Critical misses" value="Exactly zero" note="cannot be waived" /><Fact label="Training attempts" value={`${facts.created.limits.maximum_training_attempts} maximum`} note="duplicate spend blocked" /><Fact label="GPU-time ceiling" value={`${facts.created.limits.maximum_gpu_minutes} minutes`} note="Modal credential stays server-side" /></div><div className="walkthrough-rule"><span>RELEASE AUTHORITY</span><strong>Deterministic code only</strong><p>Gemini 3.6 Flash and the ADK repair fleet can author evidence-bounded curriculum. They cannot approve their own work.</p></div></>}

        {step === 3 && <div className="walkthrough-ready"><div className="ready-seal"><span>✓ CONTRACT SEALED</span><code>{mission.manifestId}</code></div><div className="ready-chain"><span><b>6</b> hash-chained journal entries</span><span><b>{facts.curriculum.parallel_agents}</b> Gemini repair specialists</span><span><b>{facts.trained.attempts?.length}</b> bounded training attempt</span><span><b>0</b> deployment permissions</span></div><div className="ready-head"><span>VERIFIED TERMINAL HEAD</span><code>{shortHash(mission.headHash)}</code></div><button className="walkthrough-replay-button" type="button" onClick={() => onReplay(mission)}><span>▶</span><div><strong>Replay verified mission</strong><small>Watch the actual evidence advance to the refusal gate</small></div><b>↗</b></button><p className="ready-note">Read-only replay · no training spend · no mocked outcome</p></div>}

        <footer className="walkthrough-nav"><button type="button" disabled={step === 0} onClick={() => go(step - 1)}>Back</button>{step < STEPS.length - 1 && <button className="primary" type="button" onClick={() => go(step + 1)}>Continue →</button>}</footer>
      </section>
      <aside className="walkthrough-proof"><div className="proof-head"><span>SEALED CONTRACT</span><b>VERIFIED</b></div><dl><div><dt>Mission</dt><dd>{mission.id}</dd></div><div><dt>Manifest</dt><dd>{mission.manifestId}</dd></div><div><dt>Baseline errors</dt><dd>{facts.diagnosed.observed_error_count}</dd></div><div><dt>Repair fleet</dt><dd>{facts.curriculum.parallel_agents} Gemini ADK agents</dd></div><div><dt>Training</dt><dd>{facts.trained.executor} · {facts.trained.attempts?.[0]?.runtime_seconds}s</dd></div><div><dt>Final state</dt><dd className="refused-copy">Refused · not deployed</dd></div></dl><div className="proof-foot"><span>JOURNAL HEAD</span><code>{shortHash(mission.headHash)}</code><small>Allowlisted public projection</small></div></aside>
    </div>
  </main>;
}

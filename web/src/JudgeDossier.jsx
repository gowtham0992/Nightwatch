import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { fetchVerificationReceipt, requestVerification } from './data/missionAdapter.js';
import { discoveryEvidence, dossierFacts, evaluationEvidence, missionRecord, releaseChecks } from './data/judgeDossier.js';
import { SELF_SERVICE_MISSION_ID } from './data/missionControl.js';
import { shortHash } from './data/scamMission.js';
import { scrollToElementThen } from './utils/scrollGate.js';
import './judgeDossier.css';

const STAGE_LABELS = Object.freeze({
  created: 'Baseline discovered',
  diagnosed: 'Failure diagnosed',
  curriculum_ready: 'Repair curriculum sealed',
  trained: 'Candidate trained',
  evaluated: 'Frozen evidence scored',
  rejected: 'Release refused',
  promoted: 'Candidate qualified',
});

function score(value) {
  return Number.isFinite(value) ? `${(value * 100).toFixed(1)}%` : '—';
}

function Chapter({ number, kicker, title, copy, children, id }) {
  return <section className="nw-chapter" id={id}>
    <div className="nw-chapter-heading">
      <span>{String(number).padStart(2, '0')} / {kicker}</span>
      <div><h2>{title}</h2>{copy && <p>{copy}</p>}</div>
    </div>
    {children}
  </section>;
}

function CaseSwitch({ story, onSelectStory }) {
  const refusal = story !== 'qualified';
  return <div className="nw-case-switch" aria-label="Choose a verified Nightwatch outcome">
    <span>Verified cases</span>
    <button type="button" className={refusal ? 'active' : ''} aria-pressed={refusal} onClick={() => onSelectStory(SELF_SERVICE_MISSION_ID)}>Refused repair</button>
    <button type="button" className={!refusal ? 'active' : ''} aria-pressed={!refusal} onClick={() => onSelectStory('qualified')}>Qualified repair</button>
  </div>;
}

function BoundaryPreview({ qualified }) {
  return <aside className={`nw-boundary-preview ${qualified ? 'qualified' : 'refused'}`} aria-label="Nightwatch release boundary">
    <div className="nw-preview-head"><span>Release boundary</span><b>Locked by contract</b></div>
    <div className="nw-preview-model"><span>Production</span><strong>Gemma scam detector</strong><small>unchanged</small></div>
    <div className="nw-preview-line"><span>No agent can cross</span></div>
    <div className="nw-preview-model candidate"><span>Candidate 01</span><strong>{qualified ? 'Qualified' : 'Refused'}</strong><small>not deployed</small></div>
    <p>Gemini proposes below the line. Deterministic code decides whether it opens.</p>
  </aside>;
}

function Hero({ mission, facts, qualified, story, onSelectStory, onStartGate }) {
  const criticalMisses = releaseChecks(mission).find((check) => check.id === 'require_zero_critical_misses')?.measured;
  return <section className="nw-hero" id="top">
    <div className="nw-hero-copy">
      <CaseSwitch story={story} onSelectStory={onSelectStory} />
      <div className="nw-hero-kicker"><span>Verified Google Cloud mission</span><code>{mission.id}</code></div>
      <h1>{qualified ? <>This repair earned the line.<em>A human still decides deployment.</em></> : <>Nightwatch stopped a dangerous AI repair.<em>Production never saw it.</em></>}</h1>
      <p>{qualified
        ? 'The same autonomous repair fleet passed every frozen invariant. Nightwatch qualified the candidate, sealed the evidence, and stopped before deployment.'
        : `A Gemini diagnostician declared three capabilities. Agent Registry resolved the pinned specialists, private A2A carried their work, and the gate found ${criticalMisses} critical misses before refusing the repair.`}</p>
      <div className="nw-hero-actions">
        <button type="button" className="nw-primary" onClick={onStartGate}>{qualified ? 'Run the passing gate' : 'Run the refusal gate'} <span>→</span></button>
        <a href="#mission">Follow the mission</a>
      </div>
      <small>Read-only evidence replay · no training spend · no deployment authority</small>
      <div className="nw-stack-line" aria-label="Google technology stack">
        <span>Google stack</span>
        <p>{qualified
          ? 'Gemini 3.6 Flash · Google ADK · Cloud Run · Tasks · Firestore'
          : 'Gemini 3.6 Flash · Google ADK · Agent Registry · A2A · Cloud Run · Tasks · Firestore'}</p>
      </div>
    </div>
    <BoundaryPreview qualified={qualified} />
    <dl className="nw-hero-proof">
      <div><dt>Execution</dt><dd>{facts.graph.length} accountable nodes</dd></div>
      <div><dt>{qualified ? 'Repair design' : 'Agent fleet'}</dt><dd>{qualified ? `${mission.retained?.evidence?.repairBatches} Gemini-authored batches` : `${facts.specialists.length} Registry agents over A2A`}</dd></div>
      <div><dt>Evidence</dt><dd>{facts.caseCount} frozen cases</dd></div>
      <div><dt>Release</dt><dd>{qualified ? '4 / 4 passed' : '4 / 4 failed'}</dd></div>
    </dl>
  </section>;
}

function ContractStrip({ mission, facts }) {
  return <section className="nw-contract" aria-label="Frozen repair mission contract">
    <div><span>Frozen contract</span><strong>{mission.manifestId}</strong></div>
    <dl>
      <div><dt>Model</dt><dd>{mission.model}</dd></div>
      <div><dt>Evidence</dt><dd>{facts.caseCount} cases · target / safety / regression</dd></div>
      <div><dt>Compute</dt><dd>{facts.trainingAttempts} attempt · {facts.gpuMinutes} GPU min max</dd></div>
      <div><dt>Deployment</dt><dd>not authorised</dd></div>
    </dl>
  </section>;
}

function Discovery({ mission, facts }) {
  const evidence = discoveryEvidence(mission);
  const scores = evidence.scores;
  return <div className="nw-discovery-grid">
    <div className="nw-discovery-statement"><strong>{facts.baselineErrors ?? '—'}</strong><p>wrong decisions discovered by Nightwatch before any repair agent was summoned.</p></div>
    <dl className="nw-score-grid">
      <div><dt>Target suite</dt><dd>{score(scores.target?.accuracy)}</dd><small>{scores.target?.correct ?? '—'} / {scores.target?.total ?? '—'} correct</small></div>
      <div><dt>Safety suite</dt><dd>{score(scores.safety?.accuracy)}</dd><small>{scores.safety?.correct ?? '—'} / {scores.safety?.total ?? '—'} correct</small></div>
      <div><dt>Regression suite</dt><dd>{score(scores.regression?.accuracy)}</dd><small>{scores.regression?.correct ?? '—'} / {scores.regression?.total ?? '—'} correct</small></div>
    </dl>
    <div className="nw-authority-note"><span>Gemini 3.6 Flash · Google ADK</span><blockquote>“{evidence.diagnosis}”</blockquote><p>Allowed: author additive curriculum. Forbidden: change evidence, policy, compute, or deployment.</p></div>
  </div>;
}

function RetainedCurriculum({ mission }) {
  const retained = mission.retained;
  const design = retained.stages.find((stage) => stage.id === 'design');
  return <div className="nw-retained-curriculum">
    <div><span>Gemini 3.6 Flash · Google ADK</span><h3>{design.headline}</h3><p>{design.summary}</p></div>
    <dl>
      <div><dt>Validated rows</dt><dd>{retained.evidence.curriculumRows}</dd></div>
      <div><dt>Repair batches</dt><dd>{retained.evidence.repairBatches}</dd></div>
      <div><dt>Maximum similarity</dt><dd>{retained.evidence.maximumSimilarity.toFixed(3)}</dd></div>
      <div><dt>Curriculum SHA</dt><dd><code>{shortHash(retained.hashes.curriculum)}</code></dd></div>
    </dl>
  </div>;
}

function SpecialistFleet({ facts }) {
  const [selectedId, setSelectedId] = useState(facts.specialists[0]?.id);
  useEffect(() => { setSelectedId(facts.specialists[0]?.id); }, [facts.specialists]);
  const selected = facts.specialists.find((specialist) => specialist.id === selectedId) || facts.specialists[0];
  return <div className="nw-fleet">
    <div className="nw-diagnostician"><span>01</span><div><small>Gemini diagnostician · Google ADK</small><strong>Declared three capabilities; Agent Registry matched only the frozen roster.</strong></div></div>
    <div className="nw-fleet-connector" aria-hidden="true"><span /></div>
    <div className="nw-specialists" aria-label="Registry-discovered private A2A specialist agents">
      {facts.specialists.map((specialist, index) => <button type="button" key={specialist.id} className={selected?.id === specialist.id ? 'active' : ''} aria-pressed={selected?.id === specialist.id} onClick={() => setSelectedId(specialist.id)}>
        <span>0{index + 2}</span><small>{specialist.receipt ? 'Registry agent · private A2A' : 'Gemini specialist'}</small><strong>{specialist.name}</strong><p>{specialist.assignment}</p><div className="nw-specialist-receipt"><b>{specialist.rows} sealed rows</b><code>SHA {shortHash(specialist.hash)}</code></div>
      </button>)}
    </div>
    {selected && <div className="nw-selected-artifact" aria-live="polite"><div><span>{selected.receipt ? 'A2A receipt + sealed artifact' : 'Selected sealed artifact'}</span><code>{selected.hash}</code></div><p>{selected.rows} independently authored rows survived schema, uniqueness, and leakage validation before the curriculum was merged.</p>{selected.receipt && <p><b>Agent Card</b> {shortHash(selected.receipt.agent_card_sha256)} · <b>request</b> {shortHash(selected.receipt.request_sha256)} · <b>response</b> {shortHash(selected.receipt.response_sha256)}</p>}</div>}
  </div>;
}

function Evaluation({ mission, facts }) {
  const evidence = evaluationEvidence(mission);
  if (!evidence) return <div className="nw-empty-evidence">Evaluation evidence is not available.</div>;
  const { rows } = evidence;
  return <div className={`nw-evaluation ${mission.outcome === 'qualified' ? 'qualified' : ''}`}>
    <aside><span>One bounded attempt</span><strong>{evidence.runtimeSeconds}s</strong><p>{evidence.executor} trained candidate-01 from {evidence.examples ?? facts.curriculumRows} validated examples. The frozen contract allowed no second try.</p><dl><div><dt>Executor</dt><dd>{evidence.executor}</dd></div><div><dt>Attempts</dt><dd>{evidence.attempts}</dd></div><div><dt>Production</dt><dd>isolated</dd></div></dl></aside>
    <div className="nw-eval-table"><div className="nw-eval-row header"><span>Frozen suite</span><span>Baseline</span><span>Candidate</span><span>Change</span></div>{rows.map(({ suite, baseline, candidate }) => <div className="nw-eval-row" key={suite}><strong>{suite}</strong><span>{baseline?.correct} / {baseline?.total}<b>{score(baseline?.accuracy)}</b></span><span>{candidate?.correct} / {candidate?.total}<b>{score(candidate?.accuracy)}</b></span><em>{Number.isFinite(candidate?.accuracy - baseline?.accuracy) ? `${((candidate.accuracy - baseline.accuracy) * 100).toFixed(1)} pp` : '—'}</em></div>)}</div>
  </div>;
}

function ReleaseBoundary({ mission, qualified, runToken }) {
  const checks = useMemo(() => releaseChecks(mission), [mission]);
  const [step, setStep] = useState(0);
  const [running, setRunning] = useState(false);
  const handledRunTokenRef = useRef(runToken);
  const resolved = Math.min(step, checks.length);
  const complete = resolved === checks.length;
  const run = useCallback(() => { setStep(0); setRunning(true); }, []);
  useEffect(() => {
    if (handledRunTokenRef.current === runToken) return;
    handledRunTokenRef.current = runToken;
    run();
  }, [run, runToken]);
  useEffect(() => {
    if (!running) return undefined;
    const reduced = globalThis.matchMedia?.('(prefers-reduced-motion: reduce)').matches;
    if (reduced) { setStep(checks.length); setRunning(false); return undefined; }
    if (step >= checks.length) { setRunning(false); return undefined; }
    const timer = globalThis.setTimeout(() => setStep((value) => value + 1), 620);
    return () => globalThis.clearTimeout(timer);
  }, [checks.length, running, step]);
  const progress = qualified ? 10 + resolved * 20.5 : 10 + resolved * 15.5;
  return <div className={`nw-release ${qualified ? 'qualified' : 'refused'} ${complete ? 'complete' : ''}`}>
    <div className="nw-release-summary"><div><span>Deterministic code only</span><h3>{complete ? qualified ? 'Four of four passed. The line can open.' : 'Four of four failed. The line stays shut.' : running ? `Checking invariant ${resolved + 1} of ${checks.length}.` : 'The candidate reaches the line no agent can cross.'}</h3></div><b>{complete ? qualified ? 'QUALIFIED · NOT DEPLOYED' : 'REFUSED · PRODUCTION PRESERVED' : 'RELEASE PENDING'}</b></div>
    <div className="nw-release-track" aria-hidden="true"><span className="nw-candidate" style={{ '--candidate-progress': progress }}>candidate-01</span><i /><div><strong>Release line</strong><small>{complete ? qualified ? 'open for human review' : 'closed by evidence' : 'awaiting invariants'}</small></div></div>
    <ol className="nw-checks">{checks.map((check, index) => {
      const done = index < resolved;
      const active = running && index === resolved;
      return <li key={check.id} className={done ? check.pass ? 'pass' : 'fail' : active ? 'active' : 'pending'}><div><span>0{index + 1}</span><b>{done ? check.pass ? 'passed' : 'failed' : active ? 'checking' : 'pending'}</b></div><h4>{check.label}</h4><dl><div><dt>Required</dt><dd>{check.requirement}</dd></div><div><dt>Measured</dt><dd>{check.measured}</dd></div></dl></li>;
    })}</ol>
    <div className="nw-release-actions"><p>{complete ? qualified ? 'The candidate qualified. Nightwatch stopped here because deployment remains a human decision.' : 'Nightwatch sealed the refusal, spent no second attempt, and left the production model unchanged.' : 'All four thresholds were frozen before Gemini received an assignment.'}</p><button type="button" className="nw-primary" onClick={run} disabled={running}>{running ? 'Running checks…' : complete ? 'Run the gate again' : 'Run all four checks'} <span>→</span></button></div>
  </div>;
}

function CloudVerification({ mission }) {
  const [state, setState] = useState({ status: 'idle' });
  useEffect(() => { setState({ status: 'idle' }); }, [mission.id, mission.headHash]);
  useEffect(() => {
    if (state.status !== 'pending') return undefined;
    let cancelled = false; let timer; let attempts = 0;
    const poll = async () => {
      try {
        const receipt = await fetchVerificationReceipt(mission.id, state.verificationId);
        if (cancelled) return;
        if (receipt.status === 'verified') setState({ status: 'verified', receipt });
        else if (attempts++ < 20) timer = globalThis.setTimeout(poll, 750);
        else setState({ status: 'error', message: 'Verification timed out. The stored record remains unchanged.' });
      } catch (error) { if (!cancelled) setState({ status: 'error', message: error.message || 'Verification could not complete.' }); }
    };
    poll();
    return () => { cancelled = true; globalThis.clearTimeout(timer); };
  }, [mission.id, state.status, state.verificationId]);
  const verify = async () => {
    setState({ status: 'queueing' });
    try {
      const accepted = await requestVerification(mission.id, mission.headHash, 'judge-cloud-proof');
      setState({ status: 'pending', verificationId: accepted.verification_id });
    } catch (error) { setState({ status: 'error', message: error.message || 'Verification could not start.' }); }
  };
  const busy = ['queueing', 'pending'].includes(state.status);
  return <aside className={`nw-cloud-verification ${state.status}`} aria-live="polite">
    <div className="nw-cloud-label"><span />Fresh Google Cloud verification</div>
    <h3>{state.status === 'verified' ? 'Chain verified.' : state.status === 'error' ? 'Verification did not complete.' : busy ? 'Re-reading the chain…' : 'Don’t trust the page. Re-read the record.'}</h3>
    <p>{state.status === 'verified' ? `All ${state.receipt.entry_count} Firestore entries recomputed to the same terminal head, and a new receipt was sealed in Cloud Storage.` : state.status === 'error' ? state.message : 'A bounded Cloud Task recomputes the Firestore chain and seals a fresh receipt. It starts no training.'}</p>
    <dl><div><dt>Firestore chain</dt><dd>{state.status === 'verified' ? `${state.receipt.entry_count} / ${state.receipt.entry_count}` : busy ? 're-reading' : 'ready'}</dd></div><div><dt>Terminal head</dt><dd>{shortHash(state.receipt?.head_hash || mission.headHash)}</dd></div><div><dt>Cloud Storage receipt</dt><dd>{state.status === 'verified' ? 'sealed' : busy ? 'waiting' : 'not requested'}</dd></div></dl>
    <button type="button" className="nw-secondary" onClick={verify} disabled={busy}>{busy ? 'Verifying on Google Cloud…' : state.status === 'verified' ? 'Verify again' : state.status === 'error' ? 'Retry verification' : 'Verify on Google Cloud'}</button>
  </aside>;
}

function EvidenceRecord({ mission, facts, qualified }) {
  const record = missionRecord(mission);
  const [openHash, setOpenHash] = useState('');
  if (qualified) return <div className="nw-qualified-proof"><span>Retained counter-proof</span><h3>Qualified. Not deployed.</h3><p>This real mission passed target, safety, regression, and critical-miss checks. Its sealed head remains available for inspection; Nightwatch still stopped short of deployment.</p><code>{mission.headHash}</code></div>;
  return <div className="nw-record-grid"><ol className="nw-record">{record.map((entry, index) => <li key={entry.hash}><span>{String(index + 1).padStart(2, '0')}</span><div><strong>{STAGE_LABELS[entry.stage] || entry.stage}</strong><small>{entry.actor}</small><button type="button" onClick={() => setOpenHash((current) => current === entry.hash ? '' : entry.hash)} aria-expanded={openHash === entry.hash}>{openHash === entry.hash ? entry.hash : shortHash(entry.hash)}</button></div></li>)}</ol><CloudVerification mission={mission} /></div>;
}

export default function JudgeDossier({ mission, story, onSelectStory }) {
  const qualified = story === 'qualified' || mission.outcome === 'qualified';
  const facts = useMemo(() => dossierFacts(mission), [mission]);
  const [runToken, setRunToken] = useState(0);
  const cancelGateScrollRef = useRef(() => {});
  useEffect(() => () => cancelGateScrollRef.current(), []);
  const startGate = () => {
    cancelGateScrollRef.current();
    const boundary = globalThis.document?.getElementById('boundary');
    const reducedMotion = globalThis.matchMedia?.('(prefers-reduced-motion: reduce)').matches ?? false;
    cancelGateScrollRef.current = scrollToElementThen(boundary, () => {
      cancelGateScrollRef.current = () => {};
      setRunToken((value) => value + 1);
    }, { reducedMotion });
  };
  return <main className="nw-dossier">
    <Hero mission={mission} facts={facts} qualified={qualified} story={story} onSelectStory={onSelectStory} onStartGate={startGate} />
    <ContractStrip mission={mission} facts={facts} />
    <Chapter number={1} kicker="Autonomous discovery" title="Nightwatch found the failure itself." copy="The repair did not begin from a score typed into a demo. The pinned Gemma model was measured against the frozen contract first." id="mission"><Discovery mission={mission} facts={facts} /></Chapter>
    <Chapter number={2} kicker="Agent orchestration" title={qualified ? 'Gemini designed a bounded curriculum.' : 'Registry discovery became three private A2A jobs.'} copy={qualified ? 'The retained passing case preserves its real five-batch repair design, validation totals, and content-addressed curriculum.' : 'The diagnosis named capabilities, not endpoints. Agent Registry resolved the exact frozen identities; each specialist returned a separately hashed A2A receipt before anything was merged.'}>{qualified ? <RetainedCurriculum mission={mission} /> : <SpecialistFleet facts={facts} />}</Chapter>
    <Chapter number={3} kicker="Bounded repair" title="One candidate. No hidden retries." copy="Nightwatch spent the single training attempt the operator authorised, then evaluated the result against exactly the same evidence."><Evaluation mission={mission} facts={facts} /></Chapter>
    <Chapter number={4} kicker="The release boundary" title="The agents finish. The evidence takes over." copy="This is the separation Nightwatch exists to enforce: Gemini can design a repair, but it cannot relax a threshold or approve its own work." id="boundary"><ReleaseBoundary key={mission.id} mission={mission} qualified={qualified} runToken={runToken} /></Chapter>
    <Chapter number={5} kicker="Verifiable record" title={qualified ? 'The gate can say yes.' : 'Six handoffs. One tamper-evident chain.'} copy={qualified ? 'Passing the boundary qualifies a candidate for human review; it does not deploy it.' : `The completed mission ran in ${facts.durationSeconds} seconds. Every entry carries the hash of the one before it, ending at the exact head below.`} id="proof"><EvidenceRecord mission={mission} facts={facts} qualified={qualified} /></Chapter>
    {!qualified && <section className="nw-counterproof"><div><span>Counter-proof</span><h2>A safety gate that only says “no” is theatre.</h2><p>Nightwatch has also qualified a real repair against the same four deterministic invariants. It still did not deploy it.</p></div><button type="button" onClick={() => onSelectStory('qualified')}>Inspect the qualified repair <span>→</span></button></section>}
    {qualified && <section className="nw-counterproof return"><div><span>Primary case</span><h2>Now inspect the repair Nightwatch refused.</h2><p>The refusal proves the agents cannot grade their own work or push a candidate through a broken boundary.</p></div><button type="button" onClick={() => onSelectStory(SELF_SERVICE_MISSION_ID)}>Return to the refusal <span>→</span></button></section>}
    <section className="nw-closing"><strong>Gemini proposes.</strong><strong>Evidence persists.</strong><strong>Code decides.</strong><p>Nightwatch · autonomous repair infrastructure for specialised AI models</p></section>
  </main>;
}

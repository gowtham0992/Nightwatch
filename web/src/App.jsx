import { useEffect, useMemo, useState } from 'react';
import {
  buildAgentGraph,
  fetchMission,
  getHealth,
  JUDGE_LIVE_MISSION_ID,
  missionAtEntry,
  missionMetrics,
  retainedMission,
  SELF_SERVICE_MISSION_ID,
} from './data/missionControl.js';
import { shortHash } from './data/scamMission.js';
import { fetchVerificationReceipt, requestVerification } from './data/missionAdapter.js';
import MissionBuilder from './MissionBuilder.jsx';

const REPLAY_FRAMES = [1, 2, 3, 3.1, 3.2, 3.3, 3.4, 4, 5, 6];
const REPLAY_DELAYS = [1800, 2500, 1500, 1500, 1500, 1500, 1700, 3100, 2500];
const THEME_KEY = 'nightwatch-theme';

function initialTheme() {
  try {
    const stored = globalThis.localStorage?.getItem(THEME_KEY);
    if (stored === 'dark' || stored === 'light') return stored;
  } catch {
    // Storage can be unavailable in locked-down browser contexts.
  }
  return globalThis.matchMedia?.('(prefers-color-scheme: light)').matches ? 'light' : 'dark';
}

function Mark() { return <span className="mark" aria-hidden="true"><i /><i /><i /></span>; }
function TinyIcon({ kind }) {
  if (kind === 'arrow') return <svg viewBox="0 0 16 16" aria-hidden="true"><path d="M3 8h9m-3-4 4 4-4 4" /></svg>;
  if (kind === 'check') return <svg viewBox="0 0 16 16" aria-hidden="true"><path d="m3 8 3 3 7-7" /></svg>;
  if (kind === 'blocked') return <svg viewBox="0 0 16 16" aria-hidden="true"><path d="M4 4l8 8m0-8-8 8" /></svg>;
  return <svg viewBox="0 0 16 16" aria-hidden="true"><circle cx="8" cy="8" r="5" /></svg>;
}
function Header({ health, onNewMission, theme, onToggleTheme }) {
  return <header className="topbar">
    <a className="wordmark" href="#top"><img src="/nightwatch-logo.png" alt="Nightwatch" /></a>
    <div className="environment"><span className={health?.status === 'ok' ? 'signal online' : 'signal'} /><span>{health?.visibility === 'private' ? 'OPERATOR CLOUD' : 'REAL RUN'}</span><b>CLOUD RUN</b>{!health?.operator_enabled && <b>READ ONLY</b>}</div>
    <nav aria-label="Mission sections">{health?.operator_enabled && <button type="button" onClick={onNewMission}>New mission</button>}<button className="theme-toggle" type="button" onClick={onToggleTheme} aria-label={`Switch to ${theme === 'dark' ? 'light' : 'dark'} mode`} title={`Switch to ${theme === 'dark' ? 'Snowfield' : 'Night'} mode`}><span aria-hidden="true">{theme === 'dark' ? '☼' : '◐'}</span><b>{theme === 'dark' ? 'Snowfield' : 'Night'}</b></button><a href="#mission">Mission</a><a href="#proof">Proof</a><a href="https://github.com/gowtham0992/Nightwatch" target="_blank" rel="noreferrer">Source ↗</a></nav>
  </header>;
}

function storyFromLocation() {
  const params = new URLSearchParams(globalThis.location?.search || '');
  if (params.get('story') === 'qualified') return 'qualified';
  return params.get('mission') || SELF_SERVICE_MISSION_ID;
}

function viewFromLocation(operatorEnabled = null) {
  const params = new URLSearchParams(globalThis.location?.search || '');
  if (params.get('new') === '1') return 'builder';
  if (params.has('mission') || params.has('story') || params.has('replay') || params.get('demo') === '1') return 'mission';
  if (operatorEnabled == null) return 'auto';
  return 'mission';
}

function StorySwitch({ story, onSelect }) {
  return <div className="story-switch" aria-label="Choose a verified mission outcome">
    <span>CASE FILE</span>
    <button type="button" className={story === SELF_SERVICE_MISSION_ID ? 'active refused' : ''} onClick={() => onSelect(SELF_SERVICE_MISSION_ID)}><i />Agent proof</button>
    <button type="button" className={story === JUDGE_LIVE_MISSION_ID ? 'active refused' : ''} onClick={() => onSelect(JUDGE_LIVE_MISSION_ID)}><i />Hidden regression</button>
    <button type="button" className={story === 'qualified' ? 'active' : ''} onClick={() => onSelect('qualified')}><i />Qualified repair</button>
  </div>;
}

function MissionHeader({ mission, health, launchState, onNewMission, onWalkthrough, story, onSelectStory }) {
  const isRunning = mission.outcome === 'running' || launchState === 'launching';
  const isJudgeRefusal = mission.id === JUDGE_LIVE_MISSION_ID;
  const isSelfService = mission.id === SELF_SERVICE_MISSION_ID;
  return <section className="mission-header" id="top">
    <div className="mission-title">
      <StorySwitch story={story} onSelect={onSelectStory} />
      <div className="eyebrow"><span>MISSION / {mission.id}</span><span>{mission.mode === 'live' ? 'LIVE JOURNAL' : 'VERIFIED RUN'}</span></div>
      <h1>{isJudgeRefusal ? <>It hit 100%.<br /><em>We still refused it.</em></> : isSelfService ? <>The agents did the work.<br /><em>The gate said no.</em></> : <>Repair the model.<br /><em>Protect the boundary.</em></>}</h1>
      <p>{isJudgeRefusal ? 'In this live run, Nightwatch diagnosed a failing Gemma scam detector, assembled three Gemini repair specialists, trained one bounded candidate, then caught a hidden regression and kept production locked.' : isSelfService ? 'An operator selected Gemma, supplied a real 92-case dataset, mapped three evidence suites, froze the compute and release contract, and clicked Run. Nightwatch discovered 14 baseline failures, ran the full repair fleet, then refused the unsafe candidate.' : 'Nightwatch autonomously diagnoses a failing Gemma scam detector, assembles a specialist repair fleet, trains one bounded candidate, and hands release authority to deterministic code.'}</p>
      <div className="mission-actions">
        {health?.operator_enabled ? <button className="launch-button" type="button" onClick={onNewMission}><span>＋</span>New repair mission</button> : <><button className="launch-button" type="button" onClick={onWalkthrough}><span>▶</span>Try guided self-service</button><a className="secondary-action" href="#mission">Inspect evidence ↓</a></>}
        <span className="action-note">{health?.operator_enabled ? 'Model + dataset → autonomous repair · max 1 GPU attempt' : 'Read-only · no training spend'}</span>
      </div>
    </div>
    <div className={`decision-orbit ${mission.outcome}`}><div className="orbit-ring"><span /></div><div className="decision-copy"><small>Release state</small><strong>{mission.outcome === 'running' ? 'WATCHING' : mission.outcome.toUpperCase()}</strong><span>{mission.outcome === 'qualified' ? 'not deployed' : mission.outcome === 'refused' ? 'production protected' : 'agents at work'}</span></div></div>
  </section>;
}

function MissionContract({ mission }) {
  if (mission.id !== SELF_SERVICE_MISSION_ID) return null;
  const created = mission.entries[0]?.payload || {};
  const curriculum = mission.entries.find((entry) => entry.stage === 'curriculum_ready')?.payload || {};
  const training = mission.entries.find((entry) => entry.stage === 'trained')?.payload || {};
  return <section className="mission-contract" aria-label="Frozen operator mission contract">
    <div className="contract-intro"><span>OPERATOR INPUT → SEALED CONTRACT</span><strong>A real mission, launched from the product.</strong><p>The public case is a redacted projection. Raw rows, credentials, model revision, and control authority remain private.</p></div>
    <dl>
      <div><dt>Model</dt><dd>{mission.model}</dd><small>revision pinned privately</small></div>
      <div><dt>Evidence</dt><dd>{created.evidence_case_count} cases</dd><small>target · safety · regression</small></div>
      <div><dt>Repair fleet</dt><dd>{curriculum.parallel_agents} Gemini specialists</dd><small>{curriculum.curriculum_rows} validated rows</small></div>
      <div><dt>Compute bound</dt><dd>{created.limits?.maximum_training_attempts} attempt</dd><small>{created.limits?.maximum_gpu_minutes} GPU-minute ceiling</small></div>
      <div><dt>Execution</dt><dd>{title(training.executor)}</dd><small>credentials server-side</small></div>
      <div><dt>Deployment</dt><dd>Not authorized</dd><small>deterministic gate only</small></div>
    </dl>
  </section>;
}

function RunStrip({ mission, graph }) {
  const completed = graph.filter((node) => node.status === 'complete').length;
  const progress = Math.round((completed / graph.length) * 100);
  return <div className="run-strip">
    <div><span className="strip-label">MODEL</span><strong>{mission.model}</strong></div><div><span className="strip-label">WORKFLOW</span><strong>{mission.subject}</strong></div><div><span className="strip-label">PROGRESS</span><strong>{completed}/{graph.length} execution nodes</strong></div>
    <div className="run-progress" aria-label={`${progress}% complete`}><span style={{ width: `${progress}%` }} /></div><div><span className="strip-label">HEAD</span><code>{shortHash(mission.headHash)}</code></div>
  </div>;
}

function AgentCard({ node, selected, onSelect, compact = false }) {
  const decisionClass = node.decision ? `decision-${node.decision}` : '';
  const statusLabel = node.decision || node.status;
  const icon = node.decision === 'refused' ? 'blocked' : 'check';
  return <button type="button" className={`agent-card ${node.status} ${decisionClass} ${selected ? 'selected' : ''} ${compact ? 'compact' : ''}`} onClick={() => onSelect(node.id)} aria-label={`${node.name}: ${statusLabel}`}>
    <span className="agent-state">{node.status === 'complete' ? <TinyIcon kind={icon} /> : <span />}</span><span className="agent-copy"><strong>{node.name}</strong><small>{node.role}</small></span><span className="agent-status">{statusLabel}</span>
  </button>;
}
function Connector({ active = false }) { return <div className={`connector ${active ? 'active' : ''}`}><span /><TinyIcon kind="arrow" /></div>; }
function AgentTopology({ graph, selectedId, onSelect }) {
  const watcher = graph.find((node) => node.id === 'watcher');
  const diagnostician = graph.find((node) => node.id === 'diagnostician');
  const authors = graph.filter((node) => node.lane === 'parallel');
  const rest = graph.filter((node) => !['watcher', 'diagnostician'].includes(node.id) && node.lane !== 'parallel');
  return <div className="topology" aria-label="Live multi-agent mission topology">
    <div className="topology-start"><AgentCard node={watcher} selected={selectedId === watcher.id} onSelect={onSelect} /><Connector active={watcher.status === 'complete'} /><AgentCard node={diagnostician} selected={selectedId === diagnostician.id} onSelect={onSelect} /></div>
    <Connector active={diagnostician.status === 'complete'} />
    <div className="fleet"><div className="fleet-head"><span>PARALLEL REPAIR FLEET</span><b>{authors.length} specialists</b></div><div className="fleet-cards">{authors.map((node) => <AgentCard key={node.id} node={node} compact selected={selectedId === node.id} onSelect={onSelect} />)}</div></div>
    {rest.map((node, index) => <div className="topology-tail" key={node.id}><Connector active={(index === 0 ? authors : [rest[index - 1]]).every((item) => item.status === 'complete')} /><AgentCard node={node} selected={selectedId === node.id} onSelect={onSelect} /></div>)}
  </div>;
}

function graphForPlayback(fullGraph, idle, phase) {
  return fullGraph.map((node) => {
    if (idle) return { ...node, status: 'waiting', decision: null, evidence: { payload: {} } };
    let status = 'waiting';
    if (node.id === 'watcher') status = phase === 1 ? 'active' : phase > 1 ? 'complete' : 'waiting';
    else if (node.id === 'diagnostician') status = phase === 2 ? 'active' : phase > 2 ? 'complete' : 'waiting';
    else if (node.lane === 'parallel') status = phase === 3 ? 'active' : phase > 3 ? 'complete' : 'waiting';
    else if (node.id === 'validator') status = phase === 3.4 ? 'active' : phase > 3.4 ? 'complete' : 'waiting';
    else if (node.id === 'trainer') status = phase === 4 ? 'active' : phase > 4 ? 'complete' : 'waiting';
    else if (node.id === 'evaluator') status = phase === 5 ? 'active' : phase > 5 ? 'complete' : 'waiting';
    else if (node.id === 'gate') status = phase >= 6 ? 'complete' : 'waiting';
    return status === 'waiting'
      ? { ...node, status, decision: null, evidence: { payload: {} } }
      : { ...node, status, decision: node.id === 'gate' && phase < 6 ? null : node.decision };
  });
}

function BoundaryRail({ mission, replayCursor }) {
  const complete = mission.outcome !== 'running' && replayCursor >= mission.entries.length;
  const evaluated = replayCursor >= Math.max(1, mission.entries.length - 1);
  const candidateState = complete ? mission.outcome : evaluated ? 'evaluated' : replayCursor > 0 ? 'isolated' : 'waiting';
  return <aside className={`boundary-rail ${complete ? mission.outcome : ''}`} aria-label="Locked model boundary">
    <div className="boundary-rail-head"><span>MODEL BOUNDARY</span><b>LOCKED</b></div>
    <div className="boundary-model production"><span>PRODUCTION</span><strong>Gemma scam detector</strong><small>UNCHANGED</small></div>
    <div className="boundary-divider"><span>No agent can cross this line</span></div>
    <div className="boundary-model candidate"><span>CANDIDATE</span><strong>{title(candidateState)}</strong><small>{complete ? 'NOT DEPLOYED' : 'ISOLATED'}</small></div>
    <p>No execution node has deployment authority.</p>
  </aside>;
}

function JudgeHero({ mission, replayCursor, onRun, replaying, story, onBack }) {
  const created = mission.entries?.[0]?.payload || {};
  const evaluatedScores = mission.entries?.find((entry) => entry.stage === 'evaluated')?.payload?.candidate?.scores || {};
  const evaluatedCaseCount = Object.values(evaluatedScores).reduce((total, suite) => total + (suite?.total || 0), 0);
  const caseCount = created.evidence_case_count ?? mission.retained?.evidence?.cases ?? evaluatedCaseCount;
  const baselineTarget = mission.entries?.find((entry) => entry.stage === 'evaluated')?.payload?.baseline?.scores?.target;
  const targetMisses = Number.isInteger(baselineTarget?.total) && Number.isInteger(baselineTarget?.correct)
    ? baselineTarget.total - baselineTarget.correct
    : null;
  const qualified = mission.outcome === 'qualified';
  const isAgentProof = mission.id === SELF_SERVICE_MISSION_ID;
  const criticalMisses = missionMetrics(mission)?.criticalMisses;
  return <section className="judge-hero" id="top">
    <div className="judge-copy">
      <div className="judge-eyebrow">{qualified ? `GEMMA SCAM DETECTOR · ${caseCount} FROZEN CASES` : isAgentProof ? `LIVE SELF-SERVICE MISSION · ${created.trigger?.observed_error_count ?? 14} BASELINE ERRORS` : `PRODUCTION SCAM FILTER · ${targetMisses ?? 'OBSERVED'} TARGET CASES MISSED`}</div>
      <h1>{qualified ? <>This repair passed.<br /><em>We still didn’t deploy it.</em></> : isAgentProof ? <>Three agents designed the repair.<br /><em>The gate found {criticalMisses} dangerous misses.</em></> : <>It hit 100%.<br /><em>We still refused it.</em></>}</h1>
      <p>{qualified ? 'The same bounded fleet repaired the model and passed every frozen invariant. The deterministic gate qualified the candidate—but still had no authority to deploy it.' : isAgentProof ? 'An operator froze a real Gemma model, dataset, evidence suites, and compute ceiling. Nightwatch discovered the failure, delegated three distinct repair briefs through ADK, trained once, and refused the unsafe result.' : 'Nightwatch measured a failing Gemma model, assembled three Gemini 3.6 Flash repair specialists through ADK, trained one bounded candidate, and let deterministic code—not an agent—decide release.'}</p>
      <p className="judge-value"><b>For ML platform teams:</b> one autonomous repair loop replaces manual failure triage, curriculum design, bounded retraining, regression testing, and release paperwork—without giving an agent deployment authority.</p>
      <div className="judge-actions">
        {story === 'qualified' ? <button className="launch-button" type="button" onClick={onBack}><span>←</span>Return to the live refusal</button> : <button className="launch-button judge-run" type="button" onClick={onRun} disabled={replaying}><span>{replaying ? '●' : '▶'}</span>{replaying ? 'Mission running' : replayCursor == null ? 'Run the mission' : 'Replay the mission'}</button>}
        <a className="secondary-action" href="#proof">Inspect proof ↓</a>
      </div>
      <small className="honesty-line">Replays a verified Cloud Run mission · starts no compute · invents no outcome</small>
    </div>
    <BoundaryRail mission={mission} replayCursor={replayCursor ?? 0} />
  </section>;
}

function JudgeExperience({ mission, story, replayCursor, setReplayCursor, selectedId, setSelectedId, onSelectStory }) {
  const qualified = story === 'qualified';
  const partialMission = !qualified ? missionAtEntry(mission, Math.trunc(replayCursor ?? 1)) : mission;
  const fullGraph = useMemo(() => buildAgentGraph(mission), [mission]);
  const graph = useMemo(() => qualified ? fullGraph : graphForPlayback(fullGraph, replayCursor == null, replayCursor), [fullGraph, qualified, replayCursor]);
  const selected = graph.find((node) => node.id === selectedId) || graph.find((node) => node.status === 'active') || graph[0];
  const replaying = !qualified && replayCursor != null && replayCursor < mission.entries.length;
  const runMission = () => { setSelectedId('watcher'); setReplayCursor(1); };
  const completed = graph.filter((node) => node.status === 'complete').length;
  return <main className="judge-experience">
    <JudgeHero mission={mission} replayCursor={qualified ? 0 : replayCursor} onRun={runMission} replaying={replaying} story={story} onBack={() => onSelectStory(SELF_SERVICE_MISSION_ID)} />
    <section className="judge-mission" id="mission">
      <div className="judge-mission-head"><div><span>AUTONOMOUS EXECUTION</span><h2>One mission. Accountable handoffs.</h2></div><div className="fleet-proof"><b>{completed}/9 execution nodes</b><span>3 Gemini repair specialists · 6 immutable handoffs · 1 deterministic release gate</span></div></div>
      <div className="workspace-body judge-workspace"><div className="topology-wrap"><AgentTopology graph={graph} selectedId={selected.id} onSelect={setSelectedId} /></div><EvidencePanel node={selected} /></div>
    </section>
    <OutcomeBar mission={partialMission} onSelectStory={onSelectStory} replaying={replaying} />
    {!qualified && replayCursor >= mission.entries.length && <CloudProof mission={mission} />}
    {!qualified && replayCursor >= mission.entries.length && <section className="counter-proof"><div><span>COUNTER-PROOF</span><h2>The gate can say yes.</h2><p>Run the same governed fleet against a verified repair that passed every invariant. It qualified—and still was not deployed.</p></div><button type="button" onClick={() => onSelectStory('qualified')}>See the repair that qualified <b>→</b></button></section>}
  </main>;
}

function title(value) { return String(value).split('_').map((part) => part.charAt(0).toUpperCase() + part.slice(1)).join(' '); }
function renderValue(value) {
  if (value == null) return '—';
  if (typeof value === 'boolean') return value ? 'yes' : 'no';
  if (typeof value === 'number') return Number.isInteger(value) ? String(value) : value.toFixed(3);
  if (typeof value === 'string') return value.length > 96 ? `${value.slice(0, 93)}…` : value;
  if (Array.isArray(value)) return value.map((item) => typeof item === 'string' ? title(item) : String(item)).join(' · ');
  return JSON.stringify(value);
}
function transition(before, after) { return `${percent(before)} → ${percent(after)}`; }
function evidenceRows(payload) {
  if (payload.specialist && Number.isInteger(payload.row_count)) {
    return [
      ['assignment', payload.assignment],
      ['sealed rows', payload.row_count],
      ['specialist', payload.specialist],
      ['independent artifact', payload.sealed_independently],
    ];
  }
  if (payload.baseline?.scores && payload.candidate?.scores) {
    const routineBefore = payload.baseline.label_recall?.regression?.routine?.accuracy;
    const routineAfter = payload.candidate.label_recall?.regression?.routine?.accuracy;
    const boundaryLabel = Number.isFinite(routineBefore) && Number.isFinite(routineAfter) ? 'routine recall' : 'regression accuracy';
    const boundaryValue = boundaryLabel === 'routine recall'
      ? transition(routineBefore, routineAfter)
      : transition(payload.baseline.scores.regression?.accuracy, payload.candidate.scores.regression?.accuracy);
    return [
      ['accepted', payload.accepted],
      ['target accuracy', transition(payload.baseline.scores.target?.accuracy, payload.candidate.scores.target?.accuracy)],
      ['safety accuracy', transition(payload.baseline.scores.safety?.accuracy, payload.candidate.scores.safety?.accuracy)],
      [boundaryLabel, boundaryValue],
      ['failed invariants', (payload.decision?.failed_invariants || []).map(invariantLabel)],
      ['critical misses', payload.candidate.critical_miss_count],
      ['evaluator', payload.evaluator],
    ];
  }
  if (payload.outcome && payload.decision) {
    return [
      ['outcome', payload.outcome],
      ['deployment status', payload.deployment_status],
      ['failed invariant', invariantLabel(payload.decision.failed_invariants?.[0])],
      ['release authority', payload.promotion_authority],
      ['critical misses', payload.critical_miss_count],
      ['gate policy', payload.qualified_under],
    ];
  }
  if (payload.attempts?.length) {
    const attempt = payload.attempts[0];
    return [
      ['executor', payload.executor],
      ['attempts used', `${payload.attempts.length} / ${payload.maximum_training_attempts || payload.attempts.length}`],
      ['training runtime', `${attempt.runtime_seconds ?? attempt.training_runtime_seconds}s`],
      ['training examples', attempt.examples],
      ['candidate', attempt.candidate || attempt.model_id],
      ['selection policy', payload.selection_policy],
    ];
  }
  const preferred = ['headline', 'summary', 'observed_error_count', 'repair_family', 'repair_families', 'curriculum_rows', 'leakage_check', 'accepted', 'outcome', 'deployment_status'];
  const keys = [...preferred.filter((key) => key in payload), ...Object.keys(payload).filter((key) => !preferred.includes(key) && !['manifest_id', 'artifact_uri', 'public_summary'].includes(key))].slice(0, 7);
  return keys.map((key) => [key, payload[key]]);
}

function CloudProof({ mission }) {
  const [verification, setVerification] = useState({ status: 'idle' });
  useEffect(() => { setVerification({ status: 'idle' }); }, [mission.id, mission.headHash]);
  useEffect(() => {
    if (verification.status !== 'pending') return undefined;
    let cancelled = false; let timer; let attempts = 0;
    const poll = async () => {
      try {
        const receipt = await fetchVerificationReceipt(mission.id, verification.verificationId);
        if (cancelled) return;
        if (receipt.status === 'verified') setVerification({ status: 'verified', receipt });
        else if (attempts++ < 20) timer = globalThis.setTimeout(poll, 750);
        else setVerification({ status: 'error', message: 'Cloud verification timed out. Try again.' });
      } catch (error) {
        if (!cancelled) setVerification({ status: 'error', message: error.message || 'Cloud verification failed.' });
      }
    };
    poll();
    return () => { cancelled = true; globalThis.clearTimeout(timer); };
  }, [mission.id, verification.status, verification.verificationId]);
  const verify = async () => {
    setVerification({ status: 'queueing' });
    try {
      const accepted = await requestVerification(mission.id, mission.headHash, 'judge-cloud-proof');
      setVerification({ status: 'pending', verificationId: accepted.verification_id });
    } catch (error) {
      setVerification({ status: 'error', message: error.message || 'Cloud verification failed.' });
    }
  };
  const busy = verification.status === 'queueing' || verification.status === 'pending';
  return <section className="cloud-proof" aria-live="polite">
    <div><span>LIVE GOOGLE CLOUD PROOF</span><h2>Don’t trust the animation. Re-read the record.</h2><p>This action queues a bounded Cloud Task, re-reads the Firestore hash chain, and seals a verification receipt in Cloud Storage.</p></div>
    {verification.status === 'verified' ? <div className="cloud-receipt"><span>VERIFIED ON GOOGLE CLOUD</span><strong>{verification.receipt.entry_count} journal entries</strong><code>{shortHash(verification.receipt.head_hash)}</code><small>{new Date(verification.receipt.sealed_at).toISOString()}</small></div> : <div className="cloud-action"><button type="button" onClick={verify} disabled={busy}>{busy ? 'Verifying on Cloud…' : verification.status === 'error' ? 'Retry Cloud verification' : 'Verify on Google Cloud'}</button>{verification.status === 'error' && <small>{verification.message}</small>}</div>}
  </section>;
}
function EvidencePanel({ node }) {
  const payload = node?.evidence?.payload || {};
  const rows = evidenceRows(payload);
  const result = node?.decision || node?.status;
  return <aside className="inspector" id="proof"><div className="inspector-head"><div><span>SELECTED HANDOFF</span><h3>{node?.name}</h3></div><b className={result}>{result}</b></div><p>{node?.role}{node?.decision ? ' · evaluation complete' : ''}</p>
    <div className="artifact-card"><div className="artifact-top"><span>IMMUTABLE OUTPUT</span><code>{node?.evidence?.hash ? shortHash(node.evidence.hash) : 'pending'}</code></div>{rows.length ? <dl>{rows.map(([label, value]) => <div key={label}><dt>{title(label)}</dt><dd>{renderValue(value)}</dd></div>)}</dl> : <div className="empty-artifact"><span /><p>This agent has not received its handoff yet.</p></div>}</div>
    <div className="trust-note"><TinyIcon kind="check" /><p><strong>Explainable, not performative.</strong> Every completed node points to a hash-chained journal entry or retained artifact. Internal reasoning is never exposed.</p></div>
  </aside>;
}

function percent(value) { return Number.isFinite(value) ? `${(value * 100).toFixed(1)}%` : '—'; }
function invariantLabel(value) {
  const labels = {
    minimum_target_gain: 'Target gain missed its floor',
    maximum_regression_drop: 'Regression loss exceeded its ceiling',
    minimum_safety_accuracy: 'Safety accuracy missed its floor',
    require_zero_critical_misses: 'Critical safety cases were missed',
    routine_recall_regressed: 'Routine-message recall regressed',
    safety_block_recall_below_floor: 'Safety-block recall missed its floor',
    target_gain_below_floor: 'Target gain missed its floor',
  };
  return labels[value] || 'A release invariant failed';
}
function OutcomeBar({ mission, onSelectStory, replaying }) {
  const metrics = missionMetrics(mission);
  return <section className={`outcome-bar ${mission.outcome}`}><div><span>DETERMINISTIC RELEASE GATE</span><strong>{mission.outcome === 'running' ? 'Decision pending' : mission.outcome === 'qualified' ? 'Candidate qualified' : 'Candidate refused'}</strong></div>
    {metrics ? <div className="outcome-metrics"><span>Target <b>{percent(metrics.target.before)} → {percent(metrics.target.after)}</b></span><span>Safety <b>{percent(metrics.safety.before)} → {percent(metrics.safety.after)}</b></span>{metrics.routineRecall ? <span className={metrics.failedInvariant === 'routine_recall_regressed' ? 'failed-metric' : ''}>Routine recall <b>{percent(metrics.routineRecall.before)} → {percent(metrics.routineRecall.after)}</b></span> : metrics.regression && <span className={metrics.failedInvariants?.includes('maximum_regression_drop') ? 'failed-metric' : ''}>Regression <b>{percent(metrics.regression.before)} → {percent(metrics.regression.after)}</b></span>}<span>Critical misses <b>{metrics.criticalMisses}</b></span></div> : <div className="outcome-metrics"><span>Authority <b>code only</b></span><span>Deployment <b>locked</b></span></div>}
    {metrics?.failedInvariant && <div className="gate-reason"><span>WHY IT STOPPED</span><b>{metrics.failedInvariants?.length > 1 ? `${metrics.failedInvariants.length} release invariants failed` : invariantLabel(metrics.failedInvariant)}</b></div>}
    <div className="outcome-seal"><Mark /><span>{mission.outcome === 'qualified' ? 'ALL INVARIANTS PASSED' : mission.outcome === 'refused' ? 'PRODUCTION PRESERVED' : 'AWAITING EVIDENCE'}</span></div>
    {mission.id === SELF_SERVICE_MISSION_ID && mission.outcome === 'refused' && !replaying && <button className="compare-outcome" type="button" onClick={() => onSelectStory('qualified')}><span>Compare the successful repair</span><b>Qualified case →</b></button>}
  </section>;
}

function MissionCompletion({ mission, replaying }) {
  if (mission.id !== SELF_SERVICE_MISSION_ID || mission.outcome !== 'refused' || replaying) return null;
  return <section className="mission-completion" id="completion" aria-label="Verified Nightwatch mission completion">
    <div className="completion-copy"><span>THE WATCH HAS CONCLUDED</span><strong>Unsafe repair held at the boundary.</strong><p>Six real handoffs inspected. Four release invariants failed. Production remained untouched.</p></div>
    <img src="/nightwatch-logo.png" alt="Nightwatch" />
    <div className="completion-head"><span>SEALED JOURNAL HEAD</span><code>{shortHash(mission.headHash)}</code><small>Verified public projection</small></div>
  </section>;
}

function MissionLoading({ failed, onRetry }) {
  return <main><section className="mission-loading" id="top"><span>{failed ? 'EVIDENCE UNAVAILABLE' : 'VERIFYING HASH CHAIN'}</span><h1>{failed ? 'The public record could not be loaded.' : 'Loading the live mission record…'}</h1><p>{failed ? 'Nightwatch will not substitute fixture data when public evidence is unavailable.' : 'Reading the redacted six-entry journal bound to its exact Firestore head.'}</p>{failed && <button type="button" className="launch-button" onClick={onRetry}>Retry evidence</button>}</section></main>;
}

export default function App() {
  const initialStory = storyFromLocation();
  const [theme, setTheme] = useState(initialTheme);
  const [health, setHealth] = useState(null);
  const [story, setStory] = useState(initialStory);
  const [mission, setMission] = useState(() => initialStory === 'qualified' ? retainedMission() : null);
  const [selectedId, setSelectedId] = useState('diagnostician');
  const [launchState, setLaunchState] = useState('idle');
  const [notice, setNotice] = useState('');
  const [loadFailed, setLoadFailed] = useState(false);
  const [retryNonce, setRetryNonce] = useState(0);
  const [view, setView] = useState(() => viewFromLocation());
  const [replayCursor, setReplayCursor] = useState(null);
  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    document.documentElement.style.colorScheme = theme;
    document.querySelector('meta[name="theme-color"]')?.setAttribute('content', theme === 'light' ? '#f4f1e9' : '#191d20');
    try { globalThis.localStorage?.setItem(THEME_KEY, theme); } catch { /* Keep the selected theme for this session. */ }
  }, [theme]);
  useEffect(() => { let ignore = false; getHealth().then((result) => { if (!ignore) { setHealth(result); setView((current) => current === 'auto' ? viewFromLocation(result.operator_enabled) : current); } }).catch(() => { if (!ignore) { setHealth({ status: 'offline', visibility: 'public_redacted', operator_enabled: false }); setView((current) => current === 'auto' ? 'mission' : current); } }); return () => { ignore = true; }; }, []);
  useEffect(() => {
    const onPopState = () => { setStory(storyFromLocation()); setView(viewFromLocation(health?.operator_enabled ?? false)); setReplayCursor(null); };
    globalThis.addEventListener?.('popstate', onPopState);
    return () => globalThis.removeEventListener?.('popstate', onPopState);
  }, [health?.operator_enabled]);
  useEffect(() => {
    if (story === 'qualified') {
      setMission(retainedMission()); setLaunchState('complete'); setLoadFailed(false); setNotice('');
      return undefined;
    }
    let ignore = false; let timer; let controller;
    const poll = async () => {
      controller = new AbortController();
      try { const result = await fetchMission(story, { signal: controller.signal }); if (ignore) return; setMission(result); setLoadFailed(false); setLaunchState(result.terminal ? 'complete' : 'running'); setNotice(''); if (!result.terminal) timer = globalThis.setTimeout(poll, 2000); }
      catch (error) { if (ignore) return; if (error.status === 404) { setNotice('Cloud Task accepted. Waiting for the first immutable journal entry…'); timer = globalThis.setTimeout(poll, 1500); } else { setLoadFailed(true); setNotice(error.message || 'Mission evidence is temporarily unavailable.'); } }
    };
    poll(); return () => { ignore = true; controller?.abort(); globalThis.clearTimeout(timer); };
  }, [story, retryNonce]);
  useEffect(() => {
    if (replayCursor == null || !mission || replayCursor >= mission.entries.length) return undefined;
    const reducedMotion = globalThis.matchMedia?.('(prefers-reduced-motion: reduce)').matches;
    const frameIndex = REPLAY_FRAMES.indexOf(replayCursor);
    const timer = globalThis.setTimeout(() => {
      if (reducedMotion) setReplayCursor(mission.entries.length);
      else setReplayCursor(REPLAY_FRAMES[Math.min(REPLAY_FRAMES.length - 1, frameIndex + 1)]);
    }, reducedMotion ? 100 : REPLAY_DELAYS[Math.max(0, frameIndex)]);
    return () => globalThis.clearTimeout(timer);
  }, [mission, replayCursor]);
  useEffect(() => {
    if (replayCursor != null && mission && replayCursor >= mission.entries.length) {
      setLaunchState('complete');
      setNotice('Replay complete. The deterministic gate refused the candidate and production stayed locked.');
    }
  }, [mission, replayCursor]);
  useEffect(() => {
    if (replayCursor == null || !mission?.entries?.length) return;
    const full = buildAgentGraph(mission);
    const authors = full.filter((node) => node.lane === 'parallel').map((node) => node.id);
    const focusByFrame = ['watcher', 'diagnostician', authors[0], authors[0], authors[1], authors[2], 'validator', 'trainer', 'evaluator', 'gate'];
    setSelectedId(focusByFrame[Math.max(0, REPLAY_FRAMES.indexOf(replayCursor))] || 'watcher');
  }, [mission, replayCursor]);
  const displayMission = useMemo(() => mission && replayCursor != null ? missionAtEntry(mission, replayCursor) : mission, [mission, replayCursor]);
  const graph = useMemo(() => displayMission ? buildAgentGraph(displayMission) : [], [displayMission]);
  const selected = graph.find((node) => node.id === selectedId) || graph.find((node) => node.status === 'active') || graph[0];
  const handleStory = (nextStory) => {
    const url = new URL(globalThis.location.href);
    url.searchParams.delete('mission'); url.searchParams.delete('story'); url.searchParams.delete('demo'); url.searchParams.delete('replay');
    if (nextStory === 'qualified') url.searchParams.set('story', 'qualified');
    else url.searchParams.set('mission', nextStory);
    globalThis.history.pushState({}, '', url);
    setSelectedId('diagnostician'); setNotice(''); setLoadFailed(false); setReplayCursor(null); setView('mission');
    setMission(nextStory === 'qualified' ? retainedMission() : null);
    setStory(nextStory);
  };
  const openBuilder = () => { const url = new URL(globalThis.location.href); url.searchParams.set('new', '1'); globalThis.history.pushState({}, '', url); setView('builder'); };
  const closeBuilder = () => { const url = new URL(globalThis.location.href); url.searchParams.delete('new'); globalThis.history.pushState({}, '', url); setView('mission'); };
  const handleLaunched = (result) => { const url = new URL(globalThis.location.href); url.searchParams.delete('new'); url.searchParams.set('mission', result.cycle_id); globalThis.history.pushState({}, '', url); setMission(null); setStory(result.cycle_id); setView('mission'); setLaunchState('running'); setNotice('Cloud Task accepted. Baseline scan is starting on Modal…'); };
  const header = <Header health={health} onNewMission={openBuilder} theme={theme} onToggleTheme={() => setTheme((value) => value === 'dark' ? 'light' : 'dark')} />;
  if (view === 'builder') return <div className="app-shell">{header}<MissionBuilder onCancel={closeBuilder} onLaunched={handleLaunched} /></div>;
  if (view === 'auto') return <div className="app-shell">{header}<main className="theater-loading"><span>OPENING NIGHTWATCH</span><h1>Preparing the verified mission…</h1></main></div>;
  if (!mission) return <div className="app-shell">{header}<MissionLoading failed={loadFailed} onRetry={() => { setLoadFailed(false); setRetryNonce((value) => value + 1); }} /></div>;
  if (!health?.operator_enabled) return <div className="app-shell">{header}<JudgeExperience mission={mission} story={story} replayCursor={replayCursor} setReplayCursor={setReplayCursor} selectedId={selectedId} setSelectedId={setSelectedId} onSelectStory={handleStory} /><footer><span><Mark /><strong>Nightwatch</strong></span><p>Gemini proposes. Evidence persists. Code decides.</p><code>{shortHash(mission.headHash)}</code></footer></div>;
  const replaying = replayCursor != null && mission && replayCursor < mission.entries.length;
  return <div className="app-shell">{header}<main><MissionHeader mission={displayMission} health={health} launchState={launchState} onNewMission={openBuilder} story={story} onSelectStory={handleStory} />{notice && <div className="notice"><span className="signal online" />{notice}</div>}<RunStrip mission={displayMission} graph={graph} /><MissionContract mission={displayMission} />
    <section className="mission-workspace" id="mission"><div className="workspace-heading"><div><span>AUTONOMOUS EXECUTION</span><h2>One mission. Accountable handoffs.</h2></div><p>Select any agent to inspect the evidence it handed downstream.</p></div><div className="workspace-body"><div className="topology-wrap"><AgentTopology graph={graph} selectedId={selected.id} onSelect={setSelectedId} /></div><EvidencePanel node={selected} /></div></section><OutcomeBar mission={displayMission} onSelectStory={handleStory} replaying={replaying} /><MissionCompletion mission={displayMission} replaying={replaying} /></main>
    <footer><span><Mark /><strong>Nightwatch</strong></span><p>Gemini proposes. Evidence persists. Code decides.</p><code>{shortHash(displayMission.headHash)}</code></footer></div>;
}

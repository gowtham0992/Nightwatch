import { useEffect, useMemo, useState } from 'react';
import {
  buildAgentGraph,
  fetchMission,
  getHealth,
  JUDGE_LIVE_MISSION_ID,
  launchMission,
  missionMetrics,
  retainedMission,
} from './data/missionControl.js';
import { shortHash } from './data/scamMission.js';

function Mark() { return <span className="mark" aria-hidden="true"><i /><i /><i /></span>; }
function TinyIcon({ kind }) {
  if (kind === 'arrow') return <svg viewBox="0 0 16 16" aria-hidden="true"><path d="M3 8h9m-3-4 4 4-4 4" /></svg>;
  if (kind === 'check') return <svg viewBox="0 0 16 16" aria-hidden="true"><path d="m3 8 3 3 7-7" /></svg>;
  if (kind === 'blocked') return <svg viewBox="0 0 16 16" aria-hidden="true"><path d="M4 4l8 8m0-8-8 8" /></svg>;
  return <svg viewBox="0 0 16 16" aria-hidden="true"><circle cx="8" cy="8" r="5" /></svg>;
}
function makeIdempotencyKey() {
  try {
    const existing = globalThis.sessionStorage?.getItem('nightwatch-launch-key');
    if (existing) return existing;
    const suffix = globalThis.crypto?.randomUUID?.() || `${Date.now()}-${Math.random().toString(16).slice(2)}`;
    const key = `nightwatch-${suffix}`;
    globalThis.sessionStorage?.setItem('nightwatch-launch-key', key);
    return key;
  } catch { return `nightwatch-${Date.now()}-operator`; }
}

function Header({ health }) {
  return <header className="topbar">
    <a className="wordmark" href="#top"><Mark /><strong>Nightwatch</strong></a>
    <div className="environment"><span className={health?.status === 'ok' ? 'signal online' : 'signal'} /><span>{health?.visibility === 'private' ? 'Operator cloud' : 'Public evidence'}</span><b>GCP</b></div>
    <nav aria-label="Mission sections"><a href="#mission">Mission</a><a href="#proof">Proof</a><a href="https://github.com/gowtham0992/Nightwatch" target="_blank" rel="noreferrer">Source ↗</a></nav>
  </header>;
}

function storyFromLocation() {
  const params = new URLSearchParams(globalThis.location?.search || '');
  if (params.get('story') === 'qualified') return 'qualified';
  return params.get('mission') || JUDGE_LIVE_MISSION_ID;
}

function StorySwitch({ story, onSelect }) {
  return <div className="story-switch" aria-label="Choose a verified mission outcome">
    <span>CASE FILE</span>
    <button type="button" className={story === JUDGE_LIVE_MISSION_ID ? 'active refused' : ''} onClick={() => onSelect(JUDGE_LIVE_MISSION_ID)}><i />Live refusal</button>
    <button type="button" className={story === 'qualified' ? 'active' : ''} onClick={() => onSelect('qualified')}><i />Qualified repair</button>
  </div>;
}

function MissionHeader({ mission, health, launchState, onLaunch, story, onSelectStory }) {
  const isRunning = mission.outcome === 'running' || launchState === 'launching';
  const isJudgeRefusal = mission.id === JUDGE_LIVE_MISSION_ID;
  return <section className="mission-header" id="top">
    <div className="mission-title">
      <StorySwitch story={story} onSelect={onSelectStory} />
      <div className="eyebrow"><span>MISSION / {mission.id}</span><span>{mission.mode === 'live' ? 'LIVE JOURNAL' : 'VERIFIED RUN'}</span></div>
      <h1>{isJudgeRefusal ? <>It hit 100%.<br /><em>We still refused it.</em></> : <>Repair the model.<br /><em>Protect the boundary.</em></>}</h1>
      <p>{isJudgeRefusal ? 'In this live run, Nightwatch diagnosed a failing Gemma scam detector, assembled three Gemini repair specialists, trained one bounded candidate, then caught a hidden regression and kept production locked.' : 'Nightwatch autonomously diagnoses a failing Gemma scam detector, assembles a specialist repair fleet, trains one bounded candidate, and hands release authority to deterministic code.'}</p>
      <div className="mission-actions">
        {health?.operator_enabled ? <button className="launch-button" type="button" onClick={onLaunch} disabled={isRunning}><span>{isRunning ? '◌' : '↗'}</span>{isRunning ? 'Mission in progress' : 'Launch real repair'}</button> : <a className="launch-button" href="#mission"><span>↓</span>Inspect verified mission</a>}
        <span className="action-note">{health?.operator_enabled ? '1 approved manifest · max 1 GPU attempt' : 'Read-only · no training spend'}</span>
      </div>
    </div>
    <div className={`decision-orbit ${mission.outcome}`}><div className="orbit-ring"><span /></div><div className="decision-copy"><small>Release state</small><strong>{mission.outcome === 'running' ? 'WATCHING' : mission.outcome.toUpperCase()}</strong><span>{mission.outcome === 'qualified' ? 'not deployed' : mission.outcome === 'refused' ? 'production protected' : 'agents at work'}</span></div></div>
  </section>;
}

function RunStrip({ mission, graph }) {
  const completed = graph.filter((node) => node.status === 'complete').length;
  const progress = Math.round((completed / graph.length) * 100);
  return <div className="run-strip">
    <div><span className="strip-label">MODEL</span><strong>{mission.model}</strong></div><div><span className="strip-label">WORKFLOW</span><strong>{mission.subject}</strong></div><div><span className="strip-label">PROGRESS</span><strong>{completed}/{graph.length} agents</strong></div>
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
  if (payload.baseline?.scores && payload.candidate?.scores) {
    return [
      ['accepted', payload.accepted],
      ['target accuracy', transition(payload.baseline.scores.target?.accuracy, payload.candidate.scores.target?.accuracy)],
      ['safety accuracy', transition(payload.baseline.scores.safety?.accuracy, payload.candidate.scores.safety?.accuracy)],
      ['routine recall', transition(payload.baseline.label_recall?.regression?.routine?.accuracy, payload.candidate.label_recall?.regression?.routine?.accuracy)],
      ['failed invariant', invariantLabel(payload.decision?.failed_invariants?.[0])],
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
    routine_recall_regressed: 'Routine-message recall regressed',
    safety_block_recall_below_floor: 'Safety-block recall missed its floor',
    target_gain_below_floor: 'Target gain missed its floor',
  };
  return labels[value] || 'A release invariant failed';
}
function OutcomeBar({ mission }) {
  const metrics = missionMetrics(mission);
  return <section className={`outcome-bar ${mission.outcome}`}><div><span>DETERMINISTIC RELEASE GATE</span><strong>{mission.outcome === 'running' ? 'Decision pending' : mission.outcome === 'qualified' ? 'Candidate qualified' : 'Candidate refused'}</strong></div>
    {metrics ? <div className="outcome-metrics"><span>Target <b>{percent(metrics.target.before)} → {percent(metrics.target.after)}</b></span><span>Safety <b>{percent(metrics.safety.before)} → {percent(metrics.safety.after)}</b></span>{metrics.routineRecall && <span className={metrics.failedInvariant === 'routine_recall_regressed' ? 'failed-metric' : ''}>Routine recall <b>{percent(metrics.routineRecall.before)} → {percent(metrics.routineRecall.after)}</b></span>}<span>Critical misses <b>{metrics.criticalMisses}</b></span></div> : <div className="outcome-metrics"><span>Authority <b>code only</b></span><span>Deployment <b>locked</b></span></div>}
    {metrics?.failedInvariant && <div className="gate-reason"><span>WHY IT STOPPED</span><b>{invariantLabel(metrics.failedInvariant)}</b></div>}
    <div className="outcome-seal"><Mark /><span>{mission.outcome === 'qualified' ? 'ALL INVARIANTS PASSED' : mission.outcome === 'refused' ? 'PRODUCTION PRESERVED' : 'AWAITING EVIDENCE'}</span></div></section>;
}

function MissionLoading({ failed, onRetry, story, onSelectStory }) {
  return <main><section className="mission-loading" id="top"><StorySwitch story={story} onSelect={onSelectStory} /><span>{failed ? 'EVIDENCE UNAVAILABLE' : 'VERIFYING HASH CHAIN'}</span><h1>{failed ? 'The public record could not be loaded.' : 'Loading the live mission record…'}</h1><p>{failed ? 'Nightwatch will not substitute fixture data when public evidence is unavailable.' : 'Reading the redacted six-entry journal bound to its exact Firestore head.'}</p>{failed && <button type="button" className="launch-button" onClick={onRetry}>Retry evidence</button>}</section></main>;
}

export default function App() {
  const initialStory = storyFromLocation();
  const [health, setHealth] = useState(null);
  const [story, setStory] = useState(initialStory);
  const [mission, setMission] = useState(() => initialStory === 'qualified' ? retainedMission() : null);
  const [selectedId, setSelectedId] = useState('diagnostician');
  const [launchState, setLaunchState] = useState('idle');
  const [notice, setNotice] = useState('');
  const [loadFailed, setLoadFailed] = useState(false);
  const [retryNonce, setRetryNonce] = useState(0);
  useEffect(() => { let ignore = false; getHealth().then((result) => { if (!ignore) setHealth(result); }).catch(() => { if (!ignore) setHealth({ status: 'offline', visibility: 'public_redacted', operator_enabled: false }); }); return () => { ignore = true; }; }, []);
  useEffect(() => {
    const onPopState = () => setStory(storyFromLocation());
    globalThis.addEventListener?.('popstate', onPopState);
    return () => globalThis.removeEventListener?.('popstate', onPopState);
  }, []);
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
  const graph = useMemo(() => mission ? buildAgentGraph(mission) : [], [mission]);
  const selected = graph.find((node) => node.id === selectedId) || graph.find((node) => node.status === 'active') || graph[0];
  const handleStory = (nextStory) => {
    const url = new URL(globalThis.location.href);
    url.searchParams.delete('mission'); url.searchParams.delete('story');
    if (nextStory === 'qualified') url.searchParams.set('story', 'qualified');
    else url.searchParams.set('mission', nextStory);
    globalThis.history.pushState({}, '', url);
    setSelectedId('diagnostician'); setNotice(''); setLoadFailed(false);
    setMission(nextStory === 'qualified' ? retainedMission() : null);
    setStory(nextStory);
  };
  const handleLaunch = async () => {
    setLaunchState('launching'); setNotice('Submitting one approved repair mission…');
    try { const result = await launchMission(makeIdempotencyKey()); const url = new URL(globalThis.location.href); url.searchParams.set('mission', result.cycle_id); globalThis.history.pushState({}, '', url); setNotice('Cloud Task accepted. Waiting for the first immutable journal entry…'); globalThis.location.reload(); }
    catch (error) { setLaunchState('idle'); setNotice(error.message || 'The mission could not be launched.'); }
  };
  if (!mission) return <div className="app-shell"><Header health={health} /><MissionLoading failed={loadFailed} onRetry={() => { setLoadFailed(false); setRetryNonce((value) => value + 1); }} story={story} onSelectStory={handleStory} /></div>;
  return <div className="app-shell"><Header health={health} /><main><MissionHeader mission={mission} health={health} launchState={launchState} onLaunch={handleLaunch} story={story} onSelectStory={handleStory} />{notice && <div className="notice"><span className="signal online" />{notice}</div>}<RunStrip mission={mission} graph={graph} />
    <section className="mission-workspace" id="mission"><div className="workspace-heading"><div><span>AUTONOMOUS EXECUTION</span><h2>One mission. Accountable handoffs.</h2></div><p>Select any agent to inspect the evidence it handed downstream.</p></div><div className="workspace-body"><div className="topology-wrap"><AgentTopology graph={graph} selectedId={selected.id} onSelect={setSelectedId} /></div><EvidencePanel node={selected} /></div></section><OutcomeBar mission={mission} /></main>
    <footer><span><Mark /><strong>Nightwatch</strong></span><p>Gemini proposes. Evidence persists. Code decides.</p><code>{shortHash(mission.headHash)}</code></footer></div>;
}

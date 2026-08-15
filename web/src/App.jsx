import { useEffect, useMemo, useState } from 'react';
import { buildAgentGraph, fetchMission, getHealth, launchMission, retainedMission } from './data/missionControl.js';
import { shortHash } from './data/scamMission.js';

function Mark() { return <span className="mark" aria-hidden="true"><i /><i /><i /></span>; }
function TinyIcon({ kind }) {
  if (kind === 'arrow') return <svg viewBox="0 0 16 16" aria-hidden="true"><path d="M3 8h9m-3-4 4 4-4 4" /></svg>;
  if (kind === 'check') return <svg viewBox="0 0 16 16" aria-hidden="true"><path d="m3 8 3 3 7-7" /></svg>;
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

function MissionHeader({ mission, health, launchState, onLaunch }) {
  const isRunning = mission.outcome === 'running' || launchState === 'launching';
  return <section className="mission-header" id="top">
    <div className="mission-title">
      <div className="eyebrow"><span>MISSION / {mission.id}</span><span>{mission.mode === 'live' ? 'LIVE JOURNAL' : 'VERIFIED RUN'}</span></div>
      <h1>Repair the model.<br /><em>Protect the boundary.</em></h1>
      <p>Nightwatch autonomously diagnoses a failing Gemma scam detector, assembles a specialist repair fleet, trains one bounded candidate, and hands release authority to deterministic code.</p>
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
  return <button type="button" className={`agent-card ${node.status} ${selected ? 'selected' : ''} ${compact ? 'compact' : ''}`} onClick={() => onSelect(node.id)}>
    <span className="agent-state">{node.status === 'complete' ? <TinyIcon kind="check" /> : <span />}</span><span className="agent-copy"><strong>{node.name}</strong><small>{node.role}</small></span><span className="agent-status">{node.status}</span>
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
function EvidencePanel({ node }) {
  const payload = node?.evidence?.payload || {};
  const preferred = ['headline', 'summary', 'observed_error_count', 'repair_family', 'repair_families', 'curriculum_rows', 'leakage_check', 'selected_artifact', 'accepted', 'outcome', 'deployment_status'];
  const keys = [...preferred.filter((key) => key in payload), ...Object.keys(payload).filter((key) => !preferred.includes(key) && !['manifest_id', 'artifact_uri'].includes(key))].slice(0, 7);
  return <aside className="inspector" id="proof"><div className="inspector-head"><div><span>SELECTED HANDOFF</span><h3>{node?.name}</h3></div><b className={node?.status}>{node?.status}</b></div><p>{node?.role}</p>
    <div className="artifact-card"><div className="artifact-top"><span>IMMUTABLE OUTPUT</span><code>{node?.evidence?.hash ? shortHash(node.evidence.hash) : 'pending'}</code></div>{keys.length ? <dl>{keys.map((key) => <div key={key}><dt>{title(key)}</dt><dd>{renderValue(payload[key])}</dd></div>)}</dl> : <div className="empty-artifact"><span /><p>This agent has not received its handoff yet.</p></div>}</div>
    <div className="trust-note"><TinyIcon kind="check" /><p><strong>Explainable, not performative.</strong> Every completed node points to a hash-chained journal entry or retained artifact. Internal reasoning is never exposed.</p></div>
  </aside>;
}

function OutcomeBar({ mission }) {
  return <section className={`outcome-bar ${mission.outcome}`}><div><span>DETERMINISTIC RELEASE GATE</span><strong>{mission.outcome === 'running' ? 'Decision pending' : mission.outcome === 'qualified' ? 'Candidate qualified' : 'Candidate refused'}</strong></div>
    {mission.retained ? <div className="outcome-metrics"><span>Target <b>83.3 → 100%</b></span><span>Safety <b>95.8 → 100%</b></span><span>Critical misses <b>0</b></span></div> : <div className="outcome-metrics"><span>Authority <b>code only</b></span><span>Deployment <b>locked</b></span></div>}
    <div className="outcome-seal"><Mark /><span>{mission.outcome === 'qualified' ? 'ALL INVARIANTS PASSED' : mission.outcome === 'refused' ? 'PRODUCTION PRESERVED' : 'AWAITING EVIDENCE'}</span></div></section>;
}

export default function App() {
  const [health, setHealth] = useState(null);
  const [mission, setMission] = useState(retainedMission);
  const [selectedId, setSelectedId] = useState('diagnostician');
  const [launchState, setLaunchState] = useState('idle');
  const [notice, setNotice] = useState('');
  const cycleId = new URLSearchParams(globalThis.location?.search || '').get('mission');
  useEffect(() => { let ignore = false; getHealth().then((result) => { if (!ignore) setHealth(result); }).catch(() => { if (!ignore) setHealth({ status: 'offline', visibility: 'public_redacted', operator_enabled: false }); }); return () => { ignore = true; }; }, []);
  useEffect(() => {
    if (!cycleId) return undefined;
    let ignore = false; let timer; let controller;
    const poll = async () => {
      controller = new AbortController();
      try { const result = await fetchMission(cycleId, { signal: controller.signal }); if (ignore) return; setMission(result); setLaunchState(result.terminal ? 'complete' : 'running'); setNotice(''); if (!result.terminal) timer = globalThis.setTimeout(poll, 2000); }
      catch (error) { if (ignore) return; if (error.status === 404) { setNotice('Cloud Task accepted. Waiting for the first immutable journal entry…'); timer = globalThis.setTimeout(poll, 1500); } else setNotice(error.message || 'Mission evidence is temporarily unavailable.'); }
    };
    poll(); return () => { ignore = true; controller?.abort(); globalThis.clearTimeout(timer); };
  }, [cycleId]);
  const graph = useMemo(() => buildAgentGraph(mission), [mission]);
  const selected = graph.find((node) => node.id === selectedId) || graph.find((node) => node.status === 'active') || graph[0];
  const handleLaunch = async () => {
    setLaunchState('launching'); setNotice('Submitting one approved repair mission…');
    try { const result = await launchMission(makeIdempotencyKey()); const url = new URL(globalThis.location.href); url.searchParams.set('mission', result.cycle_id); globalThis.history.pushState({}, '', url); setNotice('Cloud Task accepted. Waiting for the first immutable journal entry…'); globalThis.location.reload(); }
    catch (error) { setLaunchState('idle'); setNotice(error.message || 'The mission could not be launched.'); }
  };
  return <div className="app-shell"><Header health={health} /><main><MissionHeader mission={mission} health={health} launchState={launchState} onLaunch={handleLaunch} />{notice && <div className="notice"><span className="signal online" />{notice}</div>}<RunStrip mission={mission} graph={graph} />
    <section className="mission-workspace" id="mission"><div className="workspace-heading"><div><span>AUTONOMOUS EXECUTION</span><h2>One mission. Accountable handoffs.</h2></div><p>Select any agent to inspect the evidence it handed downstream.</p></div><div className="workspace-body"><div className="topology-wrap"><AgentTopology graph={graph} selectedId={selected.id} onSelect={setSelectedId} /></div><EvidencePanel node={selected} /></div></section><OutcomeBar mission={mission} /></main>
    <footer><span><Mark /><strong>Nightwatch</strong></span><p>Gemini proposes. Evidence persists. Code decides.</p><code>{shortHash(mission.headHash)}</code></footer></div>;
}

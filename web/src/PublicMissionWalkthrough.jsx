import { useEffect, useMemo, useState } from 'react';
import { fetchMission, SELF_SERVICE_MISSION_ID } from './data/missionControl.js';
import { buildTheaterContract, buildTheaterStages } from './data/missionTheater.js';
import { shortHash } from './data/scamMission.js';

const PLAY_DELAY = 3600;

function LoadingState({ error, onRetry, onCancel }) {
  return <main className="theater-loading">
    <span>{error ? 'VERIFIED RECORD UNAVAILABLE' : 'VERIFYING THE REAL MISSION'}</span>
    <h1>{error ? 'Nightwatch will not fake this demo.' : 'Opening Nightwatch…'}</h1>
    <p>{error || 'Checking the six-entry Cloud Run journal and its immutable hash chain.'}</p>
    <div><button type="button" onClick={onCancel}>View case study</button>{error && <button className="primary" type="button" onClick={onRetry}>Retry evidence</button>}</div>
  </main>;
}

function ModelBoundary({ stage, running }) {
  const state = stage?.candidateState || 'Waiting';
  return <aside className="theater-boundary" aria-label="Production safety boundary">
    <div className="boundary-title"><span>MODEL BOUNDARY</span><b>LOCKED</b></div>
    <div className="model-state production"><span>PRODUCTION</span><strong>Gemma scam detector</strong><small>UNCHANGED</small></div>
    <div className="boundary-line"><span>{running ? 'Agents work below this line' : 'No agent can cross this line'}</span></div>
    <div className={`model-state candidate ${state.toLowerCase().replaceAll(' ', '-')}`}><span>CANDIDATE</span><strong>{state}</strong><small>{stage?.stage === 'rejected' ? 'NOT DEPLOYED' : 'ISOLATED'}</small></div>
    <p>No agent has deployment authority.</p>
  </aside>;
}

function Timeline({ stages, cursor, onSelect }) {
  return <ol className="theater-timeline" aria-label="Nightwatch mission stages">
    {stages.map((stage, index) => <li key={stage.stage} className={index === cursor ? 'active' : index < cursor ? 'complete' : ''}>
      <button type="button" onClick={() => onSelect(index)} aria-current={index === cursor ? 'step' : undefined}>
        <span>{index < cursor ? '✓' : `0${index + 1}`}</span><b>{stage.label}</b><small>{index <= cursor ? stage.actor : 'Waiting'}</small>
      </button>
    </li>)}
  </ol>;
}

export default function PublicMissionWalkthrough({ onCancel, onInspect, onCompare }) {
  const [mission, setMission] = useState(null);
  const [error, setError] = useState('');
  const [retry, setRetry] = useState(0);
  const [cursor, setCursor] = useState(-1);
  const [paused, setPaused] = useState(false);

  useEffect(() => {
    let ignore = false;
    const controller = new AbortController();
    fetchMission(SELF_SERVICE_MISSION_ID, { signal: controller.signal })
      .then((value) => { if (!ignore) { setMission(value); setError(''); } })
      .catch((reason) => { if (!ignore) setError(reason.message || 'The verified mission could not be loaded.'); });
    return () => { ignore = true; controller.abort(); };
  }, [retry]);

  const stages = useMemo(() => buildTheaterStages(mission), [mission]);
  const contract = useMemo(() => buildTheaterContract(mission), [mission]);
  const running = cursor >= 0 && cursor < stages.length - 1;
  const complete = cursor === stages.length - 1;
  const stage = cursor >= 0 ? stages[cursor] : null;

  useEffect(() => {
    if (!running || paused) return undefined;
    const timer = globalThis.setTimeout(() => setCursor((value) => Math.min(stages.length - 1, value + 1)), PLAY_DELAY);
    return () => globalThis.clearTimeout(timer);
  }, [cursor, paused, running, stages.length]);

  if (!mission) return <LoadingState error={error} onRetry={() => { setError(''); setRetry((value) => value + 1); }} onCancel={onCancel} />;

  const start = () => { setCursor(0); setPaused(false); };
  return <main className="mission-theater" id="top">
    <div className="theater-top"><button type="button" onClick={onCancel}>Skip to full evidence →</button><div><span className="signal online" />REAL RUN · CLOUD RUN · READ ONLY</div></div>
    <section className="theater-shell">
      <div className="theater-main">
        {cursor < 0 ? <div className="theater-brief">
          <span className="theater-kicker">A 30-SECOND AUTONOMOUS REPAIR MISSION</span>
          <h1>Watch Nightwatch repair a model—<em>and refuse its own work.</em></h1>
          <p>A Gemma scam detector is failing. Nightwatch will measure the failure, summon three Gemini repair agents, train one candidate, test it against frozen safety evidence, and let deterministic code decide whether it ships.</p>
          <div className="theater-contract">
            <div><span>MODEL</span><strong>{contract.model}</strong></div>
            <div><span>FROZEN EVIDENCE</span><strong>{contract.cases} cases · {contract.errors} errors</strong></div>
            <div><span>COMPUTE LIMIT</span><strong>{contract.attempts} attempt · {contract.gpuMinutes} GPU min</strong></div>
          </div>
          <button className="theater-primary" type="button" onClick={start}><span>▶</span> Run Nightwatch</button>
          <small>Replays a verified Cloud Run mission · starts no compute · invents no outcome</small>
        </div> : <div className="theater-story" key={stage.stage} aria-live="polite">
          <div className="theater-stage-meta"><span>STAGE {cursor + 1} OF {stages.length}</span><b>{stage.actor}</b></div>
          <h1>{stage.headline}</h1>
          <p>{stage.summary}</p>
          <dl className="theater-stage-facts">{stage.facts.map(([label, value]) => <div key={label}><dt>{label}</dt><dd>{value ?? '—'}</dd></div>)}</dl>
          <div className="theater-artifact"><span>IMMUTABLE HANDOFF</span><code>{shortHash(stage.hash)}</code><b>VERIFIED</b></div>
          {complete && <div className="theater-verdict">
            <span>FINAL RELEASE DECISION</span><strong>REFUSED</strong><p>The repair looked finished. The evidence said it was unsafe. Production stayed untouched.</p>
            <div className="theater-final-actions"><button type="button" onClick={onCompare}>See a repair that qualified</button><button type="button" onClick={() => onInspect(mission)}>Inspect every handoff</button></div>
          </div>}
        </div>}
        <ModelBoundary stage={stage} running={running} />
      </div>
      {cursor >= 0 && <><Timeline stages={stages} cursor={cursor} onSelect={(index) => { setCursor(index); setPaused(true); }} />
        <div className="theater-controls"><div className="theater-progress"><span style={{ width: `${((cursor + 1) / stages.length) * 100}%` }} /></div>{!complete && <button className="theater-pause" type="button" onClick={() => setPaused((value) => !value)}>{paused ? '▶ Continue' : 'Ⅱ Pause'}</button>}{complete && <button className="theater-pause" type="button" onClick={start}>↻ Replay</button>}</div></>}
    </section>
    <div className="theater-proofline"><span><b>6</b> hash-chained handoffs</span><span><b>3</b> Gemini ADK repair agents</span><span><b>1</b> bounded Modal attempt</span><span><b>0</b> deployment permissions</span><code>{shortHash(mission.headHash)}</code></div>
  </main>;
}

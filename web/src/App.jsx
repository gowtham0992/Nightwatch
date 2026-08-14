import { useEffect, useMemo, useState } from 'react';
import { SCAM_MISSION, formatPercent, shortHash } from './data/scamMission.js';

const INITIAL_STAGE = (() => {
  const requested = new URLSearchParams(globalThis.location?.search).get('stage');
  const index = SCAM_MISSION.stages.findIndex((stage) => stage.id === requested);
  return index < 0 ? 0 : index;
})();

function BrandMark() {
  return (
    <span className="brand-mark" aria-hidden="true">
      <span /><span /><span />
    </span>
  );
}

function ArrowIcon() {
  return <svg viewBox="0 0 16 16" aria-hidden="true"><path d="M3 8h9M9 4l4 4-4 4" /></svg>;
}

function CheckIcon() {
  return <svg viewBox="0 0 16 16" aria-hidden="true"><path d="m3 8 3 3 7-7" /></svg>;
}

function Header() {
  return (
    <header className="app-header">
      <a className="brand" href="#top" aria-label="Nightwatch home">
        <BrandMark />
        <strong>Nightwatch</strong>
      </a>
      <nav aria-label="Product sections">
        <a href="#mission">Mission</a>
        <a href="#attempts">Attempts</a>
        <a href="#evidence">Evidence</a>
      </nav>
      <div className="header-state">
        <span className="live-dot" />
        Verified Cloud run
      </div>
    </header>
  );
}

function Metric({ label, before, after, detail }) {
  return (
    <div className="metric">
      <span>{label}</span>
      <div><del>{before}</del><ArrowIcon /><strong>{after}</strong></div>
      <small>{detail}</small>
    </div>
  );
}

function MissionOverview({ onReplay, isPlaying }) {
  return (
    <section className="overview" id="top">
      <div className="overview-copy">
        <div className="context-line">
          <span className="status-pill"><CheckIcon /> promoted by policy</span>
          <span>{SCAM_MISSION.model}</span>
        </div>
        <h1>{SCAM_MISSION.title}</h1>
        <p>
          Nightwatch found the failure, diagnosed its boundary, designed a repair,
          trained Gemma, and refused every candidate until one preserved the behavior
          production still needed.
        </p>
        <div className="overview-actions">
          <button type="button" className="primary-button" onClick={onReplay}>
            <span aria-hidden="true">{isPlaying ? 'Ⅱ' : '▶'}</span>
            {isPlaying ? 'Pause mission' : 'Replay autonomous run'}
          </button>
          <a className="text-link" href="#evidence">Inspect retained evidence <ArrowIcon /></a>
        </div>
        <small className="replay-note">Playback of a verified 94-second Cloud mission. It does not retrain or deploy a model.</small>
      </div>
      <div className="overview-metrics" aria-label="Baseline to candidate metrics">
        <Metric label="Target accuracy" before="83.3%" after="100%" detail="30/36 → 36/36" />
        <Metric label="Safety accuracy" before="95.8%" after="100%" detail="23/24 → 24/24" />
        <Metric label="Overall accuracy" before="84.8%" after="95.7%" detail="+10.9 percentage points" />
      </div>
    </section>
  );
}

function StageRail({ activeIndex, onSelect }) {
  return (
    <div className="stage-rail" role="tablist" aria-label="Autonomous mission stages">
      {SCAM_MISSION.stages.map((stage, index) => (
        <button
          type="button"
          role="tab"
          aria-selected={activeIndex === index}
          aria-controls="stage-panel"
          className={activeIndex === index ? 'active' : index < activeIndex ? 'passed' : ''}
          key={stage.id}
          onClick={() => onSelect(index)}
        >
          <span className="stage-node">{index < activeIndex ? <CheckIcon /> : stage.number}</span>
          <span><strong>{stage.label}</strong><small>{stage.actor}</small></span>
        </button>
      ))}
    </div>
  );
}

function StagePanel({ stage }) {
  return (
    <article className="stage-panel" id="stage-panel" role="tabpanel" key={stage.id}>
      <div className="panel-heading">
        <div>
          <span className="section-kicker">Stage {stage.number} · {stage.actor}</span>
          <h2>{stage.headline}</h2>
        </div>
        <span className={`stage-status ${stage.status}`}><CheckIcon /> {stage.status}</span>
      </div>
      <p className="stage-summary">{stage.summary}</p>
      <div className="stage-facts">
        {stage.facts.map(([label, value]) => (
          <div key={label}><span>{label}</span><strong>{value}</strong></div>
        ))}
      </div>
      <div className="evidence-line"><span>Evidence</span><code>{stage.evidence}</code></div>
    </article>
  );
}

function ReleaseGate() {
  const rules = [
    ['Target gain', '+16.7 pp', '≥ 15.0 pp'],
    ['Safety block recall', '100%', '≥ 95%'],
    ['Routine recall', '87.5%', 'no decline'],
    ['Critical misses', '0', 'required 0'],
    ['Benign blocks', '0', 'required 0'],
  ];
  return (
    <aside className="release-gate" aria-labelledby="gate-heading">
      <div className="gate-topline"><span>Deterministic release gate</span><code>policy v1</code></div>
      <div className="gate-decision">
        <span className="decision-icon"><CheckIcon /></span>
        <div><small>Final decision</small><h2 id="gate-heading">Promote</h2></div>
      </div>
      <p>Candidate-v8 satisfied every predeclared invariant. Qualification is recorded; deployment remains locked.</p>
      <div className="gate-rules">
        {rules.map(([label, value, threshold]) => (
          <div key={label}>
            <span><CheckIcon />{label}</span>
            <strong>{value}</strong>
            <small>{threshold}</small>
          </div>
        ))}
      </div>
      <div className="authority-note">
        <strong>Gemini could propose the repair.</strong>
        <span>It could not approve itself.</span>
      </div>
    </aside>
  );
}

function MissionWorkspace({ activeIndex, onSelect }) {
  return (
    <section className="mission-section" id="mission">
      <div className="section-heading">
        <div><span className="section-kicker">One mission · six accountable handoffs</span><h2>What Nightwatch actually did</h2></div>
        <p>Select a stage to inspect its retained output.</p>
      </div>
      <StageRail activeIndex={activeIndex} onSelect={onSelect} />
      <div className="workspace-grid">
        <StagePanel stage={SCAM_MISSION.stages[activeIndex]} />
        <ReleaseGate />
      </div>
    </section>
  );
}

function Attempts() {
  return (
    <section className="attempts-section" id="attempts">
      <div className="section-heading">
        <div><span className="section-kicker">Development history · no cherry picking</span><h2>Five candidates looked good. Nightwatch refused them.</h2></div>
        <p>These earlier immutable decisions earned the repair recipe used by the fresh Cloud run.</p>
      </div>
      <div className="attempt-table" role="table" aria-label="Candidate release attempts">
        <div className="attempt-row attempt-head" role="row">
          <span>Candidate</span><span>Target</span><span>Safety</span><span>Regression</span><span>Gate</span><span>Why</span>
        </div>
        {SCAM_MISSION.attempts.map((attempt) => (
          <div className={`attempt-row ${attempt.decision}`} role="row" key={attempt.id}>
            <strong>candidate-{attempt.id}</strong>
            <span>{attempt.target}</span><span>{attempt.safety}</span><span>{attempt.regression}</span>
            <b><span className="decision-dot" />{attempt.decision}</b>
            <small>{attempt.reason}</small>
          </div>
        ))}
      </div>
      <div className="science-callout">
        <span className="callout-index">!</span>
        <div><strong>Nightwatch caught its own training defect.</strong><p>A newly initialized Gemma score head was created before the seed took effect. Pipeline v3 seeded it first, enabled deterministic algorithms, and produced byte-identical predictions across controlled runs.</p></div>
        <code>7a1cb511…f8651 × 2</code>
      </div>
    </section>
  );
}

function Evidence() {
  const rows = [
    ['Verified Firestore head', SCAM_MISSION.cloudRun.headHash],
    ['Training stage artifact', SCAM_MISSION.cloudRun.trainingArtifact],
    ['Evaluation stage artifact', SCAM_MISSION.cloudRun.evaluationArtifact],
    ['Mission contract', SCAM_MISSION.hashes.mission],
    ['Frozen development set', SCAM_MISSION.hashes.development],
    ['Final curriculum', SCAM_MISSION.hashes.curriculum],
    ['Baseline predictions', SCAM_MISSION.hashes.baselinePredictions],
    ['Candidate predictions', SCAM_MISSION.hashes.candidatePredictions],
  ];
  return (
    <section className="evidence-section" id="evidence">
      <div className="section-heading">
        <div><span className="section-kicker">Content-addressed proof</span><h2>The interface is a view of retained bytes.</h2></div>
        <p>Change one source byte and its identity changes.</p>
      </div>
      <div className="evidence-grid">
        <div className="evidence-copy">
          <p>The final adapter was loaded in a fresh Modal function and replayed against the complete frozen set. Its predictions were byte-identical to the training-run evaluation.</p>
          <dl>
            <div><dt>Model</dt><dd>{SCAM_MISSION.model}</dd></div>
            <div><dt>Revision</dt><dd><code>{shortHash(SCAM_MISSION.modelRevision)}</code></dd></div>
            <div><dt>Architect</dt><dd>{SCAM_MISSION.architect} · {SCAM_MISSION.framework}</dd></div>
            <div><dt>Executor</dt><dd>{SCAM_MISSION.executor}</dd></div>
          </dl>
        </div>
        <div className="hash-list">
          {rows.map(([label, hash]) => <div key={label}><span>{label}</span><code>{shortHash(hash)}</code><CheckIcon /></div>)}
        </div>
      </div>
    </section>
  );
}

function Footer() {
  return <footer><span><BrandMark /><strong>Nightwatch</strong></span><p>Autonomous model repair with independent release authority.</p><a href="#top">Back to top ↑</a></footer>;
}

export default function App() {
  const [activeIndex, setActiveIndex] = useState(INITIAL_STAGE);
  const [isPlaying, setIsPlaying] = useState(false);
  const activeStage = SCAM_MISSION.stages[activeIndex];

  useEffect(() => {
    if (!isPlaying) return undefined;
    const timer = window.setTimeout(() => {
      if (activeIndex === SCAM_MISSION.stages.length - 1) {
        setIsPlaying(false);
        return;
      }
      setActiveIndex((index) => index + 1);
    }, 1250);
    return () => window.clearTimeout(timer);
  }, [activeIndex, isPlaying]);

  useEffect(() => {
    const url = new URL(globalThis.location.href);
    url.searchParams.set('stage', activeStage.id);
    globalThis.history.replaceState({}, '', url);
  }, [activeStage.id]);

  const progress = useMemo(() => ((activeIndex + 1) / SCAM_MISSION.stages.length) * 100, [activeIndex]);

  const selectStage = (index) => {
    setIsPlaying(false);
    setActiveIndex(index);
  };

  const toggleReplay = () => {
    if (isPlaying) {
      setIsPlaying(false);
      return;
    }
    if (activeIndex === SCAM_MISSION.stages.length - 1) setActiveIndex(0);
    setIsPlaying(true);
    document.getElementById('mission')?.scrollIntoView({ behavior: 'smooth', block: 'start' });
  };

  return (
    <div className="app-shell">
      <Header />
      <main>
        <MissionOverview onReplay={toggleReplay} isPlaying={isPlaying} />
        <div className="playback-progress" aria-hidden="true"><span style={{ width: `${progress}%` }} /></div>
        <MissionWorkspace activeIndex={activeIndex} onSelect={selectStage} />
        <Attempts />
        <Evidence />
      </main>
      <Footer />
    </div>
  );
}

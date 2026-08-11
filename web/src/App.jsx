import { useEffect, useState } from 'react';
import { DEFAULT_MISSION_ID, loadMission } from './data/missionAdapter.js';

const TONES = {
  red: { color: '#C2392F', border: '#E0B4AD', background: '#FBEFED' },
  amber: { color: '#A66A12', border: '#E2CB9C', background: '#FBF4E3' },
  neutral: { color: '#55564E', border: '#D6D3C8', background: '#F1EFE8' },
};

function Clock() {
  const [now, setNow] = useState(() => new Date());

  useEffect(() => {
    const timer = window.setInterval(() => setNow(new Date()), 1000);
    return () => window.clearInterval(timer);
  }, []);

  return <span className="clock">{now.toISOString().slice(11, 19)} UTC</span>;
}

function StatusBand({ mission }) {
  const promoted = mission.last_verdict === 'PROMOTED';
  return (
    <header className="status-band">
      <img className="brand-logo" src="/nightwatch-logo.png" alt="Nightwatch" />
      <span className="divider" />
      <span className="watching-status">
        <span className="pulse-dot" />
        <span>
          Watching <span className="measured subject">{mission.subject}</span> · {mission.display_name} {mission.status}
        </span>
      </span>
      <span className="last-verdict">
        Last verdict: <span className={`measured ${promoted ? 'promoted-text' : 'verdict-refused'}`}>{mission.last_verdict}</span> · {mission.last_verdict_time}
      </span>
      <span className="divider" />
      <Clock />
      <span className="divider" />
      <span className="evidence-chip">{mission.evidence_label}</span>
    </header>
  );
}

function MissionState({ state, onRetry }) {
  if (state.status === 'loading') {
    return (
      <main className="mission-state" aria-live="polite">
        <span className="state-kicker">VERIFYING FIRESTORE HASH CHAIN</span>
        <h1>Calling the watch…</h1>
        <p>Nightwatch is loading the hash-chained mission ledger from Google Cloud.</p>
        <span className="state-progress" aria-hidden="true" />
      </main>
    );
  }
  return (
    <main className="mission-state mission-error" role="alert">
      <span className="state-kicker">EVIDENCE UNAVAILABLE · {state.error.code}</span>
      <h1>The ledger stayed closed.</h1>
      <p>{state.error.message}</p>
      <button type="button" onClick={onRetry}>Retry verified read</button>
    </main>
  );
}

function Orientation({ copy, onDismiss }) {
  return (
    <section className="orientation">
      <span>{copy}</span>
      <button className="dismiss" type="button" aria-label="Dismiss orientation" onClick={onDismiss}>✕</button>
    </section>
  );
}

function VerdictCard({ entry, selected, onSelect }) {
  const verdict = entry.verdict;
  const promoted = verdict.decision === 'PROMOTED';
  const [summaryLead, summaryTail] = entry.summary.split(verdict.decision);
  return (
    <button
      className={`verdict-card ${selected ? 'selected' : ''} ${promoted ? 'promoted' : 'refused'}`}
      type="button"
      onClick={onSelect}
      aria-pressed={selected}
    >
      <div className="verdict-grid">
        <span className="entry-time">{entry.timestamp}</span>
        <div>
          <div className="entry-meta">
            <span className="agent-pill gate-pill">{entry.agent}</span>
            <span className="entry-hash">{entry.entry_hash}</span>
          </div>
          <div className="gate-summary">
            {summaryLead}<span className={promoted ? 'promoted-text' : 'verdict-refused'}>{verdict.decision}</span>{summaryTail}
          </div>
          <div className="invariant-heading">{verdict.heading}</div>
          <div className="invariant-table">
            {verdict.rows.map((row) => (
              <div className={`invariant-row ${row.name === 'target' && !row.result ? 'target-row' : ''}`} key={row.name}>
                <span>{row.name}</span>
                <strong>{row.value}</strong>
                <span>{row.threshold}</span>
                {row.result && <b className={row.result === 'FAIL' ? 'fail' : ''}>{row.result}</b>}
              </div>
            ))}
          </div>
          <div className="double-rule" />
          <div className="decision-block">
            <span className="decision-stamp">{verdict.decision}</span>
            <span className="decision-note">
              {verdict.decision_note.map((line) => <span key={line}>{line}</span>)}
            </span>
          </div>
          <div className="policy-line">{verdict.policyLine}</div>
          <div className="ghosts">
            {verdict.ghosts.split(verdict.decision).map((piece, index, parts) => (
              <span key={`${piece}-${index}`}>{piece}{index < parts.length - 1 && <b>{verdict.decision}</b>}</span>
            ))}
          </div>
        </div>
      </div>
    </button>
  );
}

function EntryRow({ entry, selected, onSelect }) {
  return (
    <button className={`entry-row ${selected ? 'selected' : ''}`} type="button" onClick={onSelect} aria-pressed={selected}>
      <span className="entry-time">{entry.timestamp}</span>
      <span className="entry-content">
        <span className="entry-meta">
          <span className="agent-pill">{entry.agent}</span>
          <span className="entry-hash">{entry.entry_hash}</span>
        </span>
        <span className="entry-summary">{entry.summary}</span>
      </span>
      <span className="chevron" aria-hidden="true">›</span>
    </button>
  );
}

function EvidenceLog({ mission, entries, selectedIndex, onSelect }) {
  const newest = entries.at(-1);
  return (
    <main className="log-panel">
      <div className="panel-heading log-heading">
        <span>Evidence log · {mission.display_name}</span>
        <span className="measured panel-meta">{mission.ledger_mode} · {entries.length} entries · head {newest.entry_hash}</span>
      </div>
      <div className="entry-scroll">
        {entries.slice(0, -1).map((entry, index) => (
          <EntryRow key={entry.entry_hash} entry={entry} selected={selectedIndex === index} onSelect={() => onSelect(index)} />
        ))}
        <VerdictCard entry={newest} selected={selectedIndex === entries.length - 1} onSelect={() => onSelect(entries.length - 1)} />
        <div className="next-check">
          <span className="pulse-dot" />
          <span><span className="watching-word">watching</span> · next scheduled check {mission.next_check}</span>
        </div>
      </div>
    </main>
  );
}

function EvidenceDetail({ entry, index, total }) {
  const exhibit = entry.exhibit;
  const tone = TONES[exhibit.tone];
  return (
    <aside className="detail-panel">
      <div className="panel-heading">
        <span>Evidence detail</span>
        <span className="measured panel-meta">entry {String(index + 1).padStart(2, '0')} · {entry.agent} · {entry.timestamp}</span>
      </div>
      <div className="badge-wrap">
        <span className="exhibit-badge" style={{ color: tone.color, borderColor: tone.border, background: tone.background }}>{exhibit.badge}</span>
      </div>
      <div className="exhibit-title">{exhibit.title}</div>
      <div className="raw-label">{exhibit.rawLabel}</div>
      <div className="raw-block">
        {exhibit.raw.map((line, lineIndex) => <div key={`${line}-${lineIndex}`}>{line}</div>)}
      </div>
      {exhibit.labels && (
        <div className="labels-grid">
          <span>expected</span><strong>{exhibit.labels.expected}</strong>
          <span>predicted</span><b>{exhibit.labels.predicted}<small>← critical miss</small></b>
        </div>
      )}
      <div className="detail-rule" />
      <div className="kv-table">
        {exhibit.kv.map(([key, value]) => (
          <div className="kv-row" key={key}><span>{key}</span><span>{value}</span></div>
        ))}
      </div>
      <p className="exhibit-note">{exhibit.note}</p>
      <div className="detail-spacer" />
      <div className="detail-footer">raw evidence · unredacted · entry {String(index + 1).padStart(2, '0')} of {String(total).padStart(2, '0')}</div>
    </aside>
  );
}

export default function App() {
  const [missionState, setMissionState] = useState({ status: 'loading' });
  const [selectedIndex, setSelectedIndex] = useState(0);
  const [introVisible, setIntroVisible] = useState(true);
  const [retryVersion, setRetryVersion] = useState(0);

  useEffect(() => {
    let ignore = false;
    setMissionState({ status: 'loading' });
    loadMission(DEFAULT_MISSION_ID, { force: retryVersion > 0 }).then(
      (run) => {
        if (ignore) return;
        setMissionState({ status: 'ready', run });
        setSelectedIndex(run.entries.length - 1);
      },
      (error) => {
        if (!ignore) setMissionState({ status: 'error', error });
      },
    );
    return () => { ignore = true; };
  }, [retryVersion]);

  if (missionState.status !== 'ready') {
    return <MissionState state={missionState} onRetry={() => setRetryVersion((version) => version + 1)} />;
  }

  const { run } = missionState;
  const selectedEntry = run.entries[selectedIndex];

  return (
    <div className="ledger" data-screen-label="Nightwatch — Verified Mission Ledger">
      <StatusBand mission={run.mission} />
      {introVisible && <Orientation copy={run.mission.orientation} onDismiss={() => setIntroVisible(false)} />}
      <div className="workspace">
        <EvidenceLog mission={run.mission} entries={run.entries} selectedIndex={selectedIndex} onSelect={setSelectedIndex} />
        <EvidenceDetail entry={selectedEntry} index={selectedIndex} total={run.entries.length} />
      </div>
    </div>
  );
}

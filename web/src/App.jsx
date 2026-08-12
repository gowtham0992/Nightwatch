import { useEffect, useState } from 'react';
import {
  DEFAULT_MISSION_ID,
  fetchVerificationReceipt,
  loadMission,
  requestVerification,
} from './data/missionAdapter.js';

const TONES = {
  red: { color: '#C2392F', border: '#E0B4AD', background: '#FBEFED' },
  amber: { color: '#8F5909', border: '#E2CB9C', background: '#FBF4E3' },
  neutral: { color: '#55564E', border: '#D6D3C8', background: '#F1EFE8' },
};

const STAGE_ACTIONS = ['detect', 'diagnose', 'design', 'train', 'evaluate', 'decide'];

function Clock() {
  const [now, setNow] = useState(() => new Date());

  useEffect(() => {
    const timer = window.setInterval(() => setNow(new Date()), 1000);
    return () => window.clearInterval(timer);
  }, []);

  return <span className="clock">{now.toISOString().slice(11, 19)} UTC</span>;
}

function StatusBand({ mission }) {
  const qualified = mission.last_verdict === 'QUALIFIED';
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
        Last verdict: <span className={`measured ${qualified ? 'qualified-text' : 'verdict-refused'}`}>{mission.last_verdict}</span> · {mission.last_verdict_time}
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

function MissionCommand({ mission, entries, selectedIndex, onSelect }) {
  const { outcome } = mission;
  const qualified = mission.last_verdict === 'QUALIFIED';
  return (
    <section className="mission-command" aria-labelledby="mission-title">
      <div className="command-copy">
        <span className="command-kicker">AUTONOMOUS REPAIR MISSION · COMPLETE</span>
        <h1 id="mission-title">
          {qualified ? 'Nightwatch repaired the model.' : 'Nightwatch attempted the repair.'}
          <span>{qualified ? 'Code qualified it. Nothing auto-deployed.' : 'Code refused to let it ship.'}</span>
        </h1>
        <p>
          A Gemini agent designed one bounded intervention, Modal trained {qualified ? 'the pinned candidates' : 'one pinned candidate'},
          and an immutable policy gate {qualified ? 'qualified only the model that earned it' : 'blocked release when regression evidence failed'}.
        </p>
        <div className="stack-line" aria-label="Core implementation stack">
          <span>{outcome.teacher_model}</span>
          <span>{outcome.agent_framework.replace('_', ' ')}</span>
          <span>Modal · Gemma 3</span>
          <span>Google Cloud</span>
        </div>
      </div>

      <div className={`outcome-board ${qualified ? 'qualified' : 'refused'}`} aria-label="Verified mission outcome">
        <div className="outcome-heading">
          <span>QUALIFICATION OUTCOME</span>
          <strong>{mission.last_verdict}</strong>
        </div>
        <div className="safety-shift">
          <div><span>failed candidate</span><strong>{outcome.initial_safety}</strong></div>
          <span className="shift-arrow" aria-hidden="true">→</span>
          <div><span>{qualified ? 'qualified candidate' : 'post-training candidate'}</span><strong>{outcome.qualified_safety}</strong></div>
        </div>
        <div className="outcome-foot">
          <span><strong>{outcome.safety_delta}</strong> safety change</span>
          <span><strong>{outcome.critical_misses}</strong> critical misses</span>
          <span><strong>{outcome.training_runtime}</strong> retained training</span>
        </div>
        <div className="authority-line">
          <span>{outcome.qualified_model}</span>
          <span>{outcome.promotion_authority.replaceAll('_', ' ')}</span>
        </div>
      </div>

      <nav className="mission-lifecycle" aria-label="Autonomous mission lifecycle">
        {entries.map((entry, index) => (
          <button
            className={selectedIndex === index ? 'active' : ''}
            type="button"
            key={entry.entry_hash}
            onClick={() => onSelect(index)}
            aria-pressed={selectedIndex === index}
            aria-label={`${STAGE_ACTIONS[index]}: ${entry.summary}`}
          >
            <span className="stage-index">0{index + 1}</span>
            <span className="stage-copy">
              <strong>{STAGE_ACTIONS[index]}</strong>
              <small>{entry.agent}</small>
            </span>
            <span className="stage-mark" aria-hidden="true">✓</span>
          </button>
        ))}
      </nav>
    </section>
  );
}

function VerdictCard({ entry, selected, onSelect }) {
  const verdict = entry.verdict;
  const qualified = verdict.decision === 'QUALIFIED';
  const [summaryLead, summaryTail] = entry.summary.split(verdict.decision);
  return (
    <button
      className={`verdict-card ${selected ? 'selected' : ''} ${qualified ? 'qualified' : 'refused'}`}
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
            {summaryLead}<span className={qualified ? 'qualified-text' : 'verdict-refused'}>{verdict.decision}</span>{summaryTail}
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

function LiveProofBand({ mission, state, onVerify }) {
  const busy = state.status === 'queueing' || state.status === 'pending';
  let copy = 'Re-read all six entries and seal a create-only receipt.';
  if (state.status === 'queueing') copy = 'Binding task to the current head…';
  if (state.status === 'pending') copy = 'Private worker is validating Firestore…';
  if (state.status === 'verified') {
    copy = `${state.entryCount} entries verified · receipt ${state.verificationId.slice(0, 15)}…`;
  }
  if (state.status === 'error') copy = state.message;
  const cloudSteps = [
    ['Cloud Run', 'bind head'],
    ['Cloud Tasks', 'dispatch'],
    ['Firestore', 're-read chain'],
    ['Cloud Storage', 'seal receipt'],
  ];
  const activeStep = {
    idle: -1,
    queueing: 0,
    pending: 2,
    verified: 3,
    error: -1,
  }[state.status];
  return (
    <section className={`live-proof-band verification-${state.status}`} aria-live="polite">
      <div className="verification-intro">
        <span className="verification-kicker">LIVE GOOGLE CLOUD PROOF</span>
        <strong>Don’t trust the screenshot. Verify the chain.</strong>
        <span className="verification-copy">{copy}</span>
      </div>
      <div className="cloud-proof-flow" aria-label="Verification infrastructure">
        {cloudSteps.map(([name, action], index) => (
          <div className={`${index <= activeStep ? 'reached' : ''} ${index === activeStep && busy ? 'current' : ''}`} key={name}>
            <span className="cloud-step-dot" aria-hidden="true" />
            <span><strong>{name}</strong><small>{action}</small></span>
          </div>
        ))}
      </div>
      <div className="verification-action">
        <span className="verification-head">head {mission.head_hash.slice(0, 10)}…{mission.head_hash.slice(-6)}</span>
        <button type="button" disabled={busy} onClick={onVerify}>
          {busy ? 'Proof running…' : state.status === 'verified' ? 'Run proof again' : 'Run live proof'}
        </button>
      </div>
    </section>
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

function EvidenceDetail({ entry, index, total, detailLabel }) {
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
      <div className="detail-footer">{detailLabel} · entry {String(index + 1).padStart(2, '0')} of {String(total).padStart(2, '0')}</div>
    </aside>
  );
}

export default function App() {
  const [missionState, setMissionState] = useState({ status: 'loading' });
  const [selectedIndex, setSelectedIndex] = useState(0);
  const [introVisible, setIntroVisible] = useState(true);
  const [retryVersion, setRetryVersion] = useState(0);
  const [verificationState, setVerificationState] = useState({ status: 'idle' });

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

  const verifyCurrentHead = async () => {
    if (verificationState.status === 'queueing' || verificationState.status === 'pending') return;
    setVerificationState({ status: 'queueing' });
    try {
      const idempotencyKey = `operator:ui-${globalThis.crypto.randomUUID()}`;
      const scheduled = await requestVerification(
        run.mission.cycle_id,
        run.mission.head_hash,
        idempotencyKey,
      );
      setVerificationState({ status: 'pending', verificationId: scheduled.verification_id });
      for (let attempt = 0; attempt < 16; attempt += 1) {
        const receipt = await fetchVerificationReceipt(
          run.mission.cycle_id,
          scheduled.verification_id,
        );
        if (receipt.status === 'verified') {
          if (receipt.head_hash !== run.mission.head_hash || receipt.entry_count !== run.entries.length) {
            throw new Error('The receipt does not match the visible mission.');
          }
          setVerificationState({
            status: 'verified',
            verificationId: receipt.verification_id,
            entryCount: receipt.entry_count,
          });
          return;
        }
        await new Promise((resolve) => window.setTimeout(resolve, 750));
      }
      throw new Error('The worker did not finish within the verification window.');
    } catch (error) {
      setVerificationState({
        status: 'error',
        message: error instanceof Error ? error.message : 'Verification failed.',
      });
    }
  };

  return (
    <div className="ledger" data-screen-label="Nightwatch — Verified Mission Ledger">
      <StatusBand mission={run.mission} />
      <MissionCommand
        mission={run.mission}
        entries={run.entries}
        selectedIndex={selectedIndex}
        onSelect={setSelectedIndex}
      />
      {introVisible && <Orientation copy={run.mission.orientation} onDismiss={() => setIntroVisible(false)} />}
      <LiveProofBand mission={run.mission} state={verificationState} onVerify={verifyCurrentHead} />
      <div className="workspace" id="evidence-ledger">
        <EvidenceLog
          mission={run.mission}
          entries={run.entries}
          selectedIndex={selectedIndex}
          onSelect={setSelectedIndex}
        />
        <EvidenceDetail
          entry={selectedEntry}
          index={selectedIndex}
          total={run.entries.length}
          detailLabel={run.mission.detail_label}
        />
      </div>
    </div>
  );
}

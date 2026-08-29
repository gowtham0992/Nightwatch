import { useEffect, useMemo, useRef, useState } from 'react';
import { approveFollowup, createFollowup, dispatchFollowup, fetchFollowup, uploadDataset } from './data/missionControl.js';

const INVARIANT_LABELS = {
  minimum_target_gain: 'Target gain missed its floor',
  maximum_regression_drop: 'Regression loss crossed its ceiling',
  minimum_safety_accuracy: 'Safety accuracy fell below its floor',
  require_zero_critical_misses: 'Critical safety misses were observed',
};

function newApprovalKey(draftId) {
  const suffix = globalThis.crypto?.randomUUID?.() || `${Date.now()}-${Math.random().toString(16).slice(2)}`;
  return `followup-${draftId.slice(-8)}-${suffix}`;
}

function shortHash(value) {
  return typeof value === 'string' && value.length > 20 ? `${value.slice(0, 12)}…${value.slice(-8)}` : value;
}

function Proposal({ followup }) {
  return <>
    <div className="followup-verdict">
      <span>SEALED FOLLOW-UP PROPOSAL</span>
      <h2>Nightwatch stopped.<br /><em>It did not go idle.</em></h2>
      <p>{followup.rationale}</p>
      <div className="followup-hash"><span>Draft identity</span><code>{shortHash(followup.draft_sha256)}</code></div>
    </div>
    <div className="followup-plan">
      <header><span>NEXT BOUNDED MISSION</span><b>{followup.execution_authorized ? 'AUTHORIZED' : 'NO EXECUTION AUTHORITY'}</b></header>
      <div className="followup-capabilities">{followup.repair_emphasis.map((item, index) => <article key={item.capability}>
        <span>{String(index + 1).padStart(2, '0')}</span>
        <div><strong>{item.capability.replaceAll('_', ' ')}</strong><p>{item.reason}</p></div>
        <b>{item.proposed_rows} rows</b>
      </article>)}</div>
      <div className="followup-failures"><span>WHY THE PARENT STOPPED</span>{followup.failed_invariants.map((item) => <b key={item}>{INVARIANT_LABELS[item] || item}</b>)}</div>
      <div className="followup-locks"><div><span>Fresh evidence</span><strong>Required</strong><small>Previous evaluation treated as spent</small></div><div><span>New GPU budget</span><strong>Required</strong><small>Maximum {followup.proposed_compute.maximum_gpu_minutes} minutes</small></div><div><span>Deployment</span><strong>Still locked</strong><small>A qualified child still cannot ship itself</small></div></div>
    </div>
  </>;
}

export default function GovernedFollowup({ mission, record, operator, onRecord, onLaunched }) {
  const followup = record?.followup;
  const approval = record?.approval;
  const dispatch = record?.dispatch;
  const approvalKeyRef = useRef({ draftId: '', value: '' });
  const [busy, setBusy] = useState('');
  const [error, setError] = useState('');
  const [file, setFile] = useState(null);
  const [format, setFormat] = useState('jsonl');
  const [dataset, setDataset] = useState(null);
  const [authorized, setAuthorized] = useState(false);
  const maximum = followup?.proposed_compute?.maximum_gpu_minutes || 20;
  const [gpuMinutes, setGpuMinutes] = useState(maximum);
  useEffect(() => { setGpuMinutes(maximum); }, [maximum]);
  const canApprove = Boolean(followup && dataset && authorized && !approval && !busy);
  const emphasis = useMemo(() => followup?.repair_emphasis || [], [followup]);

  if (mission?.outcome !== 'refused') return null;
  if (!followup) {
    if (!operator) return null;
    const create = async () => {
      setBusy('Drafting from the sealed gate record…'); setError('');
      try { onRecord(await createFollowup(mission.id)); }
      catch (reason) { setError(reason.message); }
      finally { setBusy(''); }
    };
    return <section className="governed-followup empty"><div><span>GOVERNED CONTINUATION</span><h2>The refusal is terminal.<br />The work does not have to be.</h2><p>This historical mission predates automatic follow-up drafting. Generate the same create-only proposal new refused missions now receive automatically.</p></div><button type="button" className="launch-button" onClick={create} disabled={Boolean(busy)}>{busy || 'Draft the next mission →'}</button>{error && <small role="alert">{error}</small>}</section>;
  }

  const upload = async () => {
    if (!file) return;
    setBusy('Freezing fresh evidence…'); setError('');
    try { setDataset(await uploadDataset(file, format)); }
    catch (reason) { setError(reason.message); }
    finally { setBusy(''); }
  };
  const approve = async () => {
    setBusy('Authorizing one child mission…'); setError('');
    try {
      const result = await approveFollowup(followup.draft_id, {
        authorize_new_budget: true,
        dataset_id: dataset.dataset_id,
        maximum_gpu_minutes: gpuMinutes,
      }, (() => {
        if (approvalKeyRef.current.draftId !== followup.draft_id) {
          approvalKeyRef.current = {
            draftId: followup.draft_id,
            value: newApprovalKey(followup.draft_id),
          };
        }
        return approvalKeyRef.current.value;
      })());
      onLaunched(result);
    } catch (reason) {
      setError(reason.message);
      try { onRecord(await fetchFollowup(mission.id)); } catch { /* Preserve the actionable queue error. */ }
      setBusy('');
    }
  };
  const retryDispatch = async () => {
    setBusy('Recovering the authorized child dispatch…'); setError('');
    try { onLaunched(await dispatchFollowup(followup.draft_id)); }
    catch (reason) { setError(reason.message); setBusy(''); }
  };

  return <section className={`governed-followup ${operator ? 'operator' : 'public'}`} id="follow-up">
    <Proposal followup={{ ...followup, repair_emphasis: emphasis }} />
    {approval && dispatch ? <div className="followup-approved"><span>OPERATOR AUTHORIZED</span><strong>Fresh evidence confirmed. Child mission queued.</strong><code>{approval.child_cycle_id}</code><button type="button" onClick={() => onLaunched?.({ cycle_id: approval.child_cycle_id })}>Open child mission →</button></div>
      : approval ? <div className="followup-approved recovery"><span>AUTHORIZATION SEALED</span><strong>The child mission has not been confirmed in Cloud Tasks.</strong><code>{approval.child_cycle_id}</code><button type="button" onClick={retryDispatch} disabled={Boolean(busy)}>{busy || 'Retry child scheduling →'}</button>{error && <small role="alert">{error}</small>}</div>
      : operator ? <aside className="followup-approval">
        <div><span>AUTHENTICATED OPERATOR ONLY</span><h3>Supply what the agents cannot.</h3><p>A different frozen evaluation and a separately approved budget are mandatory. Approval creates one hash-linked child contract.</p></div>
        <div className="followup-upload">
          <input id="followup-dataset" type="file" accept=".csv,.jsonl,.ndjson,text/csv,application/x-ndjson" onChange={(event) => { setFile(event.target.files?.[0] || null); setDataset(null); setAuthorized(false); }} />
          <label htmlFor="followup-dataset"><span>Fresh evidence</span><strong>{dataset ? `${dataset.row_count} rows frozen` : file?.name || 'Choose CSV or JSONL'}</strong><small>{dataset ? shortHash(dataset.sha256) : 'Target · regression · safety suites required'}</small></label>
          <div className="format-switch"><button type="button" className={format === 'jsonl' ? 'active' : ''} onClick={() => setFormat('jsonl')}>JSONL</button><button type="button" className={format === 'csv' ? 'active' : ''} onClick={() => setFormat('csv')}>CSV</button></div>
          <button type="button" className="primary" disabled={!file || Boolean(busy)} onClick={upload}>{dataset ? 'Evidence frozen ✓' : busy || 'Upload and verify'}</button>
        </div>
        <label className="followup-budget"><span>GPU ceiling</span><select value={gpuMinutes} onChange={(event) => setGpuMinutes(Number(event.target.value))}>{[5, 10, 15, 20].filter((value) => value <= maximum).map((value) => <option key={value} value={value}>{value} minutes</option>)}</select></label>
        <label className="followup-consent"><input type="checkbox" checked={authorized} onChange={(event) => setAuthorized(event.target.checked)} /><span><strong>Authorize one new compute budget</strong><small>This approval cannot deploy a model or authorize another retry.</small></span></label>
        <button type="button" className="run-button" disabled={!canApprove} onClick={approve}>{busy || 'Approve & launch child mission ↗'}</button>
        {error && <div className="builder-error" role="alert"><b>Follow-up held</b><span>{error}</span></div>}
      </aside>
        : <div className="followup-public-boundary"><span>AWAITING OPERATOR</span><strong>The agents have finished everything they are allowed to do.</strong><p>An authenticated human must provide a different evidence hash and explicitly fund one more attempt. Until then, this proposal cannot execute.</p></div>}
  </section>;
}

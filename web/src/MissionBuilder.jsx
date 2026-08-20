import { useEffect, useMemo, useState } from 'react';
import { freezeContract, getOperatorCapabilities, launchMission, uploadDataset } from './data/missionControl.js';

const STEPS = ['Model', 'Dataset', 'Mapping', 'Guardrails', 'Freeze & run'];
const SUITES = ['target', 'regression', 'safety'];

function idempotencyKey(contractId) {
  const suffix = globalThis.crypto?.randomUUID?.() || `${Date.now()}-${Math.random().toString(16).slice(2)}`;
  return `nightwatch-${contractId.slice(-8)}-${suffix}`;
}

function Field({ label, hint, children }) {
  return <label className="builder-field"><span>{label}</span>{children}{hint && <small>{hint}</small>}</label>;
}

function StepRail({ step, dataset, frozen }) {
  return <aside className="builder-rail"><div className="rail-kicker">NEW REPAIR MISSION</div><ol>{STEPS.map((label, index) => <li key={label} className={index === step ? 'active' : index < step || (index === 4 && frozen) ? 'done' : ''}><span>{index < step || (index === 4 && frozen) ? '✓' : index + 1}</span><div><b>{label}</b><small>{index === 1 && dataset ? `${dataset.row_count} rows frozen` : index === 4 && frozen ? 'Contract sealed' : index === step ? 'In progress' : 'Pending'}</small></div></li>)}</ol><div className="rail-boundary"><span>RELEASE BOUNDARY</span><b>No automatic deployment</b><small>Gemini may propose. Only deterministic code can qualify.</small></div></aside>;
}

function ContractPreview({ draft, dataset, frozen }) {
  const rows = [
    ['Model', draft.model?.id || 'Not selected'],
    ['Revision', draft.model?.revision?.slice(0, 12) || '—'],
    ['Dataset', dataset?.dataset_id || 'Not uploaded'],
    ['Rows', dataset?.row_count ?? '—'],
    ['Suites', SUITES.join(' · ')],
    ['Runtime', 'Modal · server-side'],
    ['Attempts', '1 maximum'],
    ['GPU cap', `${draft.compute.maximum_gpu_minutes} minutes`],
    ['Deployment', 'Locked'],
  ];
  return <aside className="contract-preview"><div className="preview-head"><span>MISSION CONTRACT</span><b className={frozen ? 'sealed' : ''}>{frozen ? 'SEALED' : 'DRAFT'}</b></div><dl>{rows.map(([key, value]) => <div key={key}><dt>{key}</dt><dd>{value}</dd></div>)}</dl>{frozen && <div className="contract-hash"><span>CONTENT ADDRESS</span><code>{frozen.contract_id}</code></div>}</aside>;
}

export default function MissionBuilder({ onCancel, onLaunched }) {
  const [capabilities, setCapabilities] = useState(null);
  const [step, setStep] = useState(0);
  const [dataset, setDataset] = useState(null);
  const [file, setFile] = useState(null);
  const [format, setFormat] = useState('jsonl');
  const [frozen, setFrozen] = useState(null);
  const [busy, setBusy] = useState('');
  const [error, setError] = useState('');
  const [draft, setDraft] = useState({
    subject: 'Scam message safety', model: null, baseline_artifact: '', instruction: 'Classify one received message by the safest immediate handling decision. Return exactly one label: block, caution, verify, or routine.',
    mapping: { id_column: '', text_column: '', label_column: '', suite_column: '', safety_critical_column: '' },
    policy: { minimum_target_gain: 0.15, maximum_regression_drop: 0, minimum_safety_accuracy: 0.95, require_zero_critical_misses: true },
    compute: { rank: 8, epochs: 3, learning_rate: 0.001, seed: 20260813, maximum_training_attempts: 1, maximum_gpu_minutes: 20 },
  });

  useEffect(() => { let ignore = false; getOperatorCapabilities().then((value) => { if (ignore) return; setCapabilities(value); const model = value.models[0]; const baseline = model.baseline_artifacts[0]; setDraft((current) => ({ ...current, model: { id: model.id, revision: model.revision }, baseline_artifact: baseline.id, instruction: baseline.instruction })); }).catch((reason) => !ignore && setError(reason.message)); return () => { ignore = true; }; }, []);
  const modelCapability = useMemo(() => capabilities?.models.find((model) => model.id === draft.model?.id), [capabilities, draft.model]);
  const canAdvance = [Boolean(draft.model && draft.baseline_artifact), Boolean(dataset), Object.entries(draft.mapping).filter(([key]) => key !== 'safety_critical_column').every(([, value]) => value), capabilities?.runtime.connected, Boolean(frozen)][step];

  const selectModel = (modelId) => {
    const model = capabilities.models.find((item) => item.id === modelId);
    const baseline = model.baseline_artifacts[0];
    setDraft((current) => ({ ...current, model: { id: model.id, revision: model.revision }, baseline_artifact: baseline.id, instruction: baseline.instruction })); setFrozen(null);
  };
  const upload = async () => {
    if (!file) return;
    setBusy('Uploading and canonicalizing dataset…'); setError('');
    try { const value = await uploadDataset(file, format); setDataset(value); setFrozen(null); const columns = value.columns; const find = (...names) => names.find((name) => columns.includes(name)) || ''; setDraft((current) => ({ ...current, mapping: { id_column: find('id', 'case_id', 'case'), text_column: find('text', 'message', 'prompt'), label_column: find('label', 'expected_label', 'expected'), suite_column: find('suite', 'split'), safety_critical_column: find('safety_critical', 'critical') } })); setStep(2); }
    catch (reason) { setError(reason.message); } finally { setBusy(''); }
  };
  const freeze = async () => {
    setBusy('Validating every boundary…'); setError('');
    try { const value = await freezeContract({ ...draft, dataset_id: dataset.dataset_id }); setFrozen(value); }
    catch (reason) { setError(reason.message); } finally { setBusy(''); }
  };
  const run = async () => {
    setBusy('Handing contract to Cloud Tasks…'); setError('');
    try { const mission = await launchMission(frozen.contract_id, idempotencyKey(frozen.contract_id)); onLaunched(mission); }
    catch (reason) { setError(reason.message); setBusy(''); }
  };

  if (!capabilities) return <main className="builder-loading"><span>OPENING OPERATOR CONTROL</span><h1>{error || 'Loading verified capabilities…'}</h1><button type="button" onClick={onCancel}>Return to case study</button></main>;
  return <main className="mission-builder"><div className="builder-top"><button type="button" onClick={onCancel}>← Case study</button><div><span className={capabilities.runtime.connected ? 'signal online' : 'signal'} />{capabilities.runtime.connected ? 'Modal connected' : 'Modal unavailable'}</div></div><div className="builder-shell"><StepRail step={step} dataset={dataset} frozen={frozen} /><section className="builder-stage">
    <header><span>STEP {step + 1} OF {STEPS.length}</span><h1>{['Choose the failing model.', 'Bring the evidence.', 'Teach Nightwatch the schema.', 'Freeze the safety boundary.', 'Review. Seal. Run.'][step]}</h1><p>{['Only pinned Gemma revisions and registered baseline adapters can enter Nightwatch.', 'Upload evaluation evidence—not training data. Nightwatch discovers the failure itself.', 'Map semantics explicitly. Target, regression, and safety evidence are all mandatory.', 'One attempt, a hard GPU ceiling, and release rules agents cannot edit.', 'The content address binds model, data, policy, and spend into one immutable mission.'][step]}</p></header>
    {step === 0 && <div className="builder-form"><Field label="Pinned Gemma model"><select value={draft.model?.id || ''} onChange={(event) => selectModel(event.target.value)}>{capabilities.models.map((model) => <option key={model.id} value={model.id}>{model.id}</option>)}</select></Field><Field label="Immutable revision"><input value={draft.model?.revision || ''} readOnly /></Field><Field label="Registered baseline adapter"><select value={draft.baseline_artifact} onChange={(event) => { const baseline = modelCapability.baseline_artifacts.find((item) => item.id === event.target.value); setDraft({ ...draft, baseline_artifact: baseline.id, instruction: baseline.instruction }); }}>{modelCapability?.baseline_artifacts.map((artifact) => <option key={artifact.id} value={artifact.id}>{artifact.id}</option>)}</select></Field><Field label="Mission name"><input value={draft.subject} maxLength="120" onChange={(event) => setDraft({ ...draft, subject: event.target.value })} /></Field></div>}
    {step === 1 && <div className="dataset-drop"><input id="dataset-file" type="file" accept=".csv,.jsonl,.ndjson,text/csv,application/x-ndjson" onChange={(event) => setFile(event.target.files?.[0] || null)} /><label htmlFor="dataset-file"><span>↑</span><strong>{file ? file.name : 'Choose a real evaluation dataset'}</strong><small>CSV or JSONL · {capabilities.dataset.maximum_bytes / 1_000_000} MB maximum · no arbitrary code</small></label><div className="format-switch"><button type="button" className={format === 'jsonl' ? 'active' : ''} onClick={() => setFormat('jsonl')}>JSONL</button><button type="button" className={format === 'csv' ? 'active' : ''} onClick={() => setFormat('csv')}>CSV</button></div><button className="primary" type="button" disabled={!file || busy} onClick={upload}>{busy || 'Upload and inspect'}</button>{dataset && <div className="dataset-proof"><b>Content-addressed</b><code>{dataset.dataset_id}</code><span>{dataset.row_count} rows · {dataset.columns.length} columns</span></div>}</div>}
    {step === 2 && <div className="builder-form mapping-grid">{Object.entries({ id_column: 'Unique ID', text_column: 'Input text', label_column: 'Expected label', suite_column: 'Evaluation suite', safety_critical_column: 'Safety critical (optional)' }).map(([key, label]) => <Field key={key} label={label}><select value={draft.mapping[key]} onChange={(event) => { setDraft({ ...draft, mapping: { ...draft.mapping, [key]: event.target.value } }); setFrozen(null); }}><option value="">Select column</option>{dataset.columns.map((column) => <option key={column}>{column}</option>)}</select></Field>)}<div className="suite-requirement"><span>REQUIRED VALUES IN SUITE COLUMN</span>{SUITES.map((suite) => <b key={suite}>✓ {suite}</b>)}</div></div>}
    {step === 3 && <div className="builder-form policy-grid"><Field label="Classification instruction"><textarea value={draft.instruction} maxLength="500" onChange={(event) => setDraft({ ...draft, instruction: event.target.value })} /></Field><Field label="Minimum target gain"><input type="number" min="0" max="1" step="0.01" value={draft.policy.minimum_target_gain} onChange={(event) => setDraft({ ...draft, policy: { ...draft.policy, minimum_target_gain: Number(event.target.value) } })} /></Field><Field label="Maximum regression drop"><input type="number" min="0" max="1" step="0.01" value={draft.policy.maximum_regression_drop} onChange={(event) => setDraft({ ...draft, policy: { ...draft.policy, maximum_regression_drop: Number(event.target.value) } })} /></Field><Field label="Minimum safety accuracy"><input type="number" min="0" max="1" step="0.01" value={draft.policy.minimum_safety_accuracy} onChange={(event) => setDraft({ ...draft, policy: { ...draft.policy, minimum_safety_accuracy: Number(event.target.value) } })} /></Field><Field label="LoRA rank"><select value={draft.compute.rank} onChange={(event) => setDraft({ ...draft, compute: { ...draft.compute, rank: Number(event.target.value) } })}>{capabilities.compute.ranks.map((value) => <option key={value}>{value}</option>)}</select></Field><Field label="Epochs"><select value={draft.compute.epochs} onChange={(event) => setDraft({ ...draft, compute: { ...draft.compute, epochs: Number(event.target.value) } })}>{capabilities.compute.epochs.map((value) => <option key={value}>{value}</option>)}</select></Field><Field label="GPU time ceiling"><select value={draft.compute.maximum_gpu_minutes} onChange={(event) => setDraft({ ...draft, compute: { ...draft.compute, maximum_gpu_minutes: Number(event.target.value) } })}>{[5, 10, 15, 20].map((value) => <option key={value} value={value}>{value} minutes</option>)}</select></Field><label className="critical-toggle"><input type="checkbox" checked={draft.policy.require_zero_critical_misses} onChange={(event) => setDraft({ ...draft, policy: { ...draft.policy, require_zero_critical_misses: event.target.checked } })} /><span><b>Require zero critical misses</b><small>This invariant cannot be waived after freezing.</small></span></label></div>}
    {step === 4 && <div className="freeze-panel"><div className="boundary-list"><div><span>01</span><p><b>Baseline scan first</b>Nightwatch must discover a real failure before agents are summoned.</p></div><div><span>02</span><p><b>One paid attempt</b>Cloud Tasks and create-only call records prevent duplicate training spend.</p></div><div><span>03</span><p><b>Code owns release</b>Gemini cannot weaken thresholds or deploy the candidate.</p></div></div>{!frozen ? <button type="button" className="seal-button" disabled={busy} onClick={freeze}>{busy || 'Validate & freeze contract'}</button> : <div className="run-ready"><span>✓ CONTRACT SEALED</span><code>{frozen.contract_id}</code><button type="button" className="run-button" disabled={busy} onClick={run}>{busy || 'Run Nightwatch ↗'}</button></div>}</div>}
    {error && <div className="builder-error" role="alert"><b>Boundary check failed</b><span>{error}</span></div>}
    <footer className="builder-nav"><button type="button" disabled={step === 0 || busy} onClick={() => setStep(step - 1)}>Back</button>{step < 4 && <button type="button" className="primary" disabled={!canAdvance || busy} onClick={() => setStep(step + 1)}>Continue →</button>}</footer>
  </section><ContractPreview draft={draft} dataset={dataset} frozen={frozen} /></div></main>;
}

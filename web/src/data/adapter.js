import evidence from './retained-v0.json';

const RETAINED_RUNS = new Map([[evidence.mission.cycle_id, evidence]]);

export function getRetainedRun(missionId) {
  const mission = RETAINED_RUNS.get(missionId);
  if (!mission) throw new Error(`Unknown retained evidence run: ${missionId}`);
  return mission;
}

export function subscribe(missionId, onEntry) {
  const mission = getRetainedRun(missionId);
  mission.entries.forEach(onEntry);
  return () => {};
}

export function subscribeFirestore(_missionId, _onEntry) {
  throw new Error('Firestore adapter is not configured.');
}

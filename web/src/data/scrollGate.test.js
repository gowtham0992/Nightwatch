import assert from 'node:assert/strict';
import test from 'node:test';
import { scrollToElementThen } from '../utils/scrollGate.js';

test('starts the gate only after smooth scrolling settles', () => {
  const positions = [640, 520, 360, 190, 80, 20, 0, 0, 0, 0];
  const frames = [];
  const calls = [];
  const target = {
    scrollIntoView: (options) => calls.push(options),
    getBoundingClientRect: () => ({ top: positions.shift() ?? 0 }),
  };
  let started = false;

  scrollToElementThen(target, () => { started = true; }, {
    requestFrame: (callback) => frames.push(callback),
  });

  assert.deepEqual(calls, [{ behavior: 'smooth', block: 'start' }]);
  assert.equal(started, false);

  while (frames.length) frames.shift()();

  assert.equal(started, true);
});

test('reduced motion scrolls instantly and starts without animation polling', () => {
  const calls = [];
  const target = {
    scrollIntoView: (options) => calls.push(options),
    getBoundingClientRect: () => ({ top: 0 }),
  };
  let started = false;

  scrollToElementThen(target, () => { started = true; }, { reducedMotion: true });

  assert.deepEqual(calls, [{ behavior: 'auto', block: 'start' }]);
  assert.equal(started, true);
});

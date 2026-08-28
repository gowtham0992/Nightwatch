export function scrollToElementThen(target, onSettled, options = {}) {
  const {
    reducedMotion = false,
    requestFrame = globalThis.requestAnimationFrame?.bind(globalThis),
    maxFrames = 180,
  } = options;

  if (!target) {
    onSettled();
    return () => {};
  }

  target.scrollIntoView({
    behavior: reducedMotion ? 'auto' : 'smooth',
    block: 'start',
  });

  if (reducedMotion || !requestFrame) {
    onSettled();
    return () => {};
  }

  let cancelled = false;
  let frameCount = 0;
  let stableFrames = 0;
  let previousTop;

  const observe = () => {
    if (cancelled) return;

    const top = target.getBoundingClientRect().top;
    frameCount += 1;

    if (Number.isFinite(previousTop) && Math.abs(top - previousTop) < 0.5) stableFrames += 1;
    else stableFrames = 0;

    previousTop = top;

    if ((frameCount >= 6 && stableFrames >= 3) || frameCount >= maxFrames) {
      onSettled();
      return;
    }

    requestFrame(observe);
  };

  requestFrame(observe);
  return () => { cancelled = true; };
}

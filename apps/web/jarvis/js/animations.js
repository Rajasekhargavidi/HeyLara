export const clamp = (value, min, max) => Math.min(max, Math.max(min, value));
export const lerp = (from, to, amount) => from + (to - from) * amount;
export const easeOutCubic = (value) => 1 - Math.pow(1 - clamp(value, 0, 1), 3);

export function createTicker(onFrame) {
  let raf = 0;
  let last = performance.now();
  const tick = (now) => {
    const delta = Math.min((now - last) / 1000, 0.1);
    last = now;
    onFrame(delta, now / 1000);
    raf = requestAnimationFrame(tick);
  };
  raf = requestAnimationFrame(tick);
  return () => cancelAnimationFrame(raf);
}

export function pulse(element, className = 'pulse') {
  if (!element) return;
  element.classList.remove(className);
  void element.offsetWidth;
  element.classList.add(className);
}

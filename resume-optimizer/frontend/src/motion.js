import { useEffect, useRef, useState } from 'react';

const rmQuery = window.matchMedia('(prefers-reduced-motion: reduce)');

/** Live-tracking prefers-reduced-motion flag. */
export function usePrefersReducedMotion() {
  const [reduced, setReduced] = useState(rmQuery.matches);
  useEffect(() => {
    const onChange = () => setReduced(rmQuery.matches);
    rmQuery.addEventListener('change', onChange);
    return () => rmQuery.removeEventListener('change', onChange);
  }, []);
  return reduced;
}

/**
 * Animated count from 0 to `target`. Jumps straight to the target under
 * reduced motion. Re-runs when `target` changes.
 */
export function useCountUp(target, duration = 900) {
  const reduced = usePrefersReducedMotion();
  const [value, setValue] = useState(reduced ? target : 0);
  const rafRef = useRef(null);

  useEffect(() => {
    if (reduced) { setValue(target); return; }
    const start = performance.now();
    const tick = (now) => {
      const t = Math.min(1, (now - start) / duration);
      const eased = 1 - Math.pow(1 - t, 3); // ease-out cubic
      setValue(Math.round(eased * target));
      if (t < 1) rafRef.current = requestAnimationFrame(tick);
    };
    rafRef.current = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(rafRef.current);
  }, [target, duration, reduced]);

  return value;
}

/** True when the device likely can't afford a WebGL scene. */
export function isLowPowerDevice() {
  if (navigator.deviceMemory && navigator.deviceMemory <= 4) return true;
  if (window.innerWidth < 768) return true;
  return false;
}

/** WebGL availability probe. */
export function hasWebGL() {
  try {
    const canvas = document.createElement('canvas');
    return !!(canvas.getContext('webgl2') || canvas.getContext('webgl'));
  } catch {
    return false;
  }
}

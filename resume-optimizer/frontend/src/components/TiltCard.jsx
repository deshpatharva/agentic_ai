import { useRef, useCallback } from 'react';
import { usePrefersReducedMotion } from '../motion';

/**
 * Pointer-tracked 3D tilt wrapper. `lifted` (e.g. during drag-over) raises
 * and scales the card. Inert under prefers-reduced-motion.
 */
export default function TiltCard({ children, lifted = false, maxTilt = 7, className }) {
  const ref = useRef(null);
  const reduced = usePrefersReducedMotion();

  const onPointerMove = useCallback((e) => {
    const el = ref.current;
    if (!el || reduced) return;
    const rect = el.getBoundingClientRect();
    const px = (e.clientX - rect.left) / rect.width - 0.5;
    const py = (e.clientY - rect.top) / rect.height - 0.5;
    el.style.transform = `perspective(900px) rotateX(${(-py * maxTilt).toFixed(2)}deg) rotateY(${(px * maxTilt).toFixed(2)}deg)`;
  }, [maxTilt, reduced]);

  const onPointerLeave = useCallback(() => {
    const el = ref.current;
    if (!el) return;
    el.style.transform = '';
  }, []);

  const liftStyle = lifted && !reduced
    ? { transform: 'perspective(900px) translateY(-6px) scale(1.02)' }
    : undefined;

  return (
    <div
      ref={ref}
      onPointerMove={lifted ? undefined : onPointerMove}
      onPointerLeave={onPointerLeave}
      className={className}
      style={{
        transition: 'transform 200ms ease, box-shadow 200ms ease',
        willChange: 'transform',
        ...liftStyle,
      }}
    >
      {children}
    </div>
  );
}

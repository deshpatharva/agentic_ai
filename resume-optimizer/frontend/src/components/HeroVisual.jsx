import { lazy, Suspense, useMemo } from 'react';
import { usePrefersReducedMotion, isLowPowerDevice, hasWebGL } from '../motion';

const HeroScene = lazy(() => import('./three/HeroScene'));

/* Static fallback: the same floating-papers composition in pure CSS.
   The float animation is killed globally under prefers-reduced-motion. */
function PaperCard({ className, accent = 'bg-primary', delay = '0s' }) {
  return (
    <div
      className={`absolute w-44 h-60 rounded-md bg-[#FFFFFF] border border-[#E4E7EA] shadow-lifted p-4 hero-float ${className}`}
      style={{ animationDelay: delay }}
    >
      <div className="w-2/3 h-2.5 bg-[#20242A] rounded-sm mb-2" />
      <div className="w-1/2 h-1.5 bg-[#6A7078]/60 rounded-sm mb-3" />
      <div className={`w-full h-1 ${accent} rounded-sm mb-3`} />
      {[5, 4.5, 5, 0, 3, 5, 4.5, 4].map((w, i) =>
        w === 0
          ? <div key={i} className="w-2/5 h-2 bg-[#20242A]/80 rounded-sm my-2" />
          : <div key={i} className="h-1.5 bg-[#6A7078]/40 rounded-sm mb-1.5" style={{ width: `${w * 16}%` }} />
      )}
    </div>
  );
}

export function StaticHero() {
  return (
    <div className="relative w-full h-full" aria-hidden="true">
      <PaperCard className="left-[6%] top-[12%] -rotate-12 opacity-80" accent="bg-hilite" delay="0.8s" />
      <PaperCard className="right-[8%] top-[22%] rotate-[9deg] opacity-90" delay="1.6s" />
      <PaperCard className="left-[32%] top-[6%] rotate-1 scale-110 z-10" />
    </div>
  );
}

/**
 * The landing hero visual. Renders the WebGL scene only on capable
 * devices with motion allowed; otherwise (and while the 3D chunk loads)
 * shows the static CSS composition. Never blocks first paint.
 */
export default function HeroVisual() {
  const reduced = usePrefersReducedMotion();
  const capable = useMemo(() => hasWebGL() && !isLowPowerDevice(), []);

  if (reduced || !capable) return <StaticHero />;

  return (
    <Suspense fallback={<StaticHero />}>
      <HeroScene />
    </Suspense>
  );
}

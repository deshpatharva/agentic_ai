import { Check } from 'lucide-react';
import { clsx } from 'clsx';

/* Stage keys mirror the backend SSE vocabulary (main.py emit calls). */
const STAGES = [
  { key: 'jd_analysis', label: 'Analyze JD' },
  { key: 'score',       label: 'Baseline' },
  { key: 'agent',       label: 'Rewrite & iterate' },
  { key: 'humanize',    label: 'Humanize' },
  { key: 'generate',    label: 'Generate' },
];

/**
 * Live pipeline tracker shown while a run is in flight. The active stage
 * pulses (CSS — disabled under reduced motion); completed stages get inked
 * checks; the latest average score ticks along underneath.
 */
export default function PipelineProgress({ stage, iteration = 0, score = null, message }) {
  const activeIdx = Math.max(0, STAGES.findIndex((s) => s.key === stage));

  return (
    <div className="my-4 max-w-md bg-card border border-line rounded-card shadow-card px-5 py-4">
      <div className="flex items-center justify-between mb-4">
        <span className="text-xs font-semibold uppercase tracking-widest text-ink-faint">Optimizing</span>
        <div className="flex items-center gap-2">
          {iteration > 0 && (
            <span className="text-[10px] font-semibold bg-accent-soft text-primary px-2 py-0.5 rounded-full">
              iteration {iteration}
            </span>
          )}
          {score != null && (
            <span className="text-xs font-mono font-bold text-ink">{score}<span className="text-ink-faint">/100</span></span>
          )}
        </div>
      </div>

      <div className="flex items-center">
        {STAGES.map((s, i) => {
          const state = i < activeIdx ? 'done' : i === activeIdx ? 'active' : 'pending';
          return (
            <div key={s.key} className={clsx('flex items-center', i > 0 && 'flex-1')}>
              {i > 0 && (
                <div className={clsx(
                  'h-px flex-1 mx-1.5 transition-colors duration-500',
                  state === 'pending' ? 'bg-line' : 'bg-primary'
                )} />
              )}
              <div className="flex flex-col items-center gap-1.5">
                <div className={clsx(
                  'w-5 h-5 rounded-full flex items-center justify-center border-2 transition-colors duration-300',
                  state === 'done'    && 'bg-primary border-primary',
                  state === 'active'  && 'border-primary bg-card',
                  state === 'pending' && 'border-line bg-card'
                )}>
                  {state === 'done' && <Check className="w-3 h-3 text-white dark:text-ink" strokeWidth={3} />}
                  {state === 'active' && <span className="w-2 h-2 rounded-full bg-primary stage-pulse" />}
                </div>
                <span className={clsx(
                  'text-[10px] leading-none whitespace-nowrap',
                  state === 'active' ? 'text-ink font-semibold' : state === 'done' ? 'text-ink-mute' : 'text-ink-faint'
                )}>
                  {s.label}
                </span>
              </div>
            </div>
          );
        })}
      </div>

      {message && <p className="mt-3 text-xs text-ink-faint truncate">{message}</p>}
    </div>
  );
}

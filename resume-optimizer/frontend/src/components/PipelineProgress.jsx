import { useEffect, useState } from 'react';
import { Check, Clock } from 'lucide-react';
import { clsx } from 'clsx';

const STAGES = [
  { key: 'jd_analysis', label: 'Analyze JD',     hint: 'Reading the job description…' },
  { key: 'score',       label: 'Score',           hint: 'Scoring your baseline resume…' },
  { key: 'agent',       label: 'Rewrite',         hint: 'AI is rewriting bullet points…' },
  { key: 'humanize',    label: 'Humanize',        hint: 'Polishing the language…' },
  { key: 'generate',    label: 'Generate',        hint: 'Building the final .docx file…' },
];

function useElapsed(running) {
  const [secs, setSecs] = useState(0);
  useEffect(() => {
    if (!running) { setSecs(0); return; }
    const t = setInterval(() => setSecs((s) => s + 1), 1000);
    return () => clearInterval(t);
  }, [running]);
  const m = Math.floor(secs / 60);
  const s = secs % 60;
  return m > 0 ? `${m}m ${s}s` : `${s}s`;
}

export default function PipelineProgress({ stage, iteration = 0, score = null, message, running = true }) {
  const elapsed = useElapsed(running);
  const activeIdx = Math.max(0, STAGES.findIndex((s) => s.key === stage));
  const activeStage = STAGES[activeIdx];

  const displayMessage = message || activeStage?.hint || 'Processing…';

  return (
    <div className="my-4 max-w-md bg-card border border-line rounded-card shadow-card px-5 py-4">
      {/* Header row */}
      <div className="flex items-center justify-between mb-3">
        <span className="text-xs font-semibold uppercase tracking-widest text-ink-faint">
          Optimizing
        </span>
        <div className="flex items-center gap-2.5">
          <span className="flex items-center gap-1 text-[10px] text-ink-faint">
            <Clock className="w-3 h-3" />
            {elapsed}
          </span>
          {iteration > 0 && (
            <span className="text-[10px] font-semibold bg-accent-soft text-primary px-2 py-0.5 rounded-full">
              iter {iteration}
            </span>
          )}
          {score != null && (
            <span className="text-xs font-mono font-bold text-ink">
              {score}<span className="text-ink-faint">/100</span>
            </span>
          )}
        </div>
      </div>

      {/* Stage track */}
      <div className="flex items-center mb-3">
        {STAGES.map((s, i) => {
          const state = i < activeIdx ? 'done' : i === activeIdx ? 'active' : 'pending';
          return (
            <div key={s.key} className={clsx('flex items-center', i > 0 && 'flex-1')}>
              {i > 0 && (
                <div className={clsx(
                  'h-px flex-1 mx-1 transition-colors duration-700',
                  state === 'pending' ? 'bg-line' : 'bg-primary/70'
                )} />
              )}
              <div className="flex flex-col items-center gap-1">
                <div className={clsx(
                  'w-5 h-5 rounded-full flex items-center justify-center border-2 transition-all duration-300',
                  state === 'done'    && 'bg-primary border-primary',
                  state === 'active'  && 'border-primary bg-card ring-2 ring-primary/20',
                  state === 'pending' && 'border-line bg-card'
                )}>
                  {state === 'done'   && <Check className="w-2.5 h-2.5 text-white dark:text-ink" strokeWidth={3} />}
                  {state === 'active' && <span className="w-2 h-2 rounded-full bg-primary stage-pulse" />}
                </div>
                <span className={clsx(
                  'font-mono text-[9px] leading-none whitespace-nowrap uppercase tracking-wide',
                  state === 'active'  ? 'text-primary font-semibold' :
                  state === 'done'    ? 'text-ink-mute' : 'text-ink-faint'
                )}>
                  {s.label}
                </span>
              </div>
            </div>
          );
        })}
      </div>

      {/* Live status line */}
      <div className="flex items-center gap-2 mt-1 min-h-[18px]">
        <span className="inline-block w-1.5 h-1.5 rounded-full bg-primary stage-pulse shrink-0" />
        <p className="text-[11px] text-ink-faint truncate">{displayMessage}</p>
      </div>
    </div>
  );
}

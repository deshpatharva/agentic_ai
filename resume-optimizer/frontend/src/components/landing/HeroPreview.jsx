import { Check } from 'lucide-react';

const SUBSCORES = [
  { label: 'ATS Match',    value: 94 },
  { label: 'Impact',       value: 88 },
  { label: 'Skills Gap',   value: 90 },
  { label: 'JD Tailoring', value: 92 },
];

const STAGES = ['JD', 'Score', 'Rewrite', 'Humanize', 'Verify', 'Export'];

/** Static, presentational preview of the optimizer result (mock data). */
export default function HeroPreview() {
  return (
    <div className="bg-card border border-line rounded-card shadow-lifted p-6 w-full max-w-md mx-auto">
      <p className="font-mono text-[10px] uppercase tracking-widest text-ink-faint mb-3">Optimization complete</p>

      <div className="flex items-end gap-3 mb-5">
        <span className="font-display text-6xl font-semibold text-primary leading-none">91</span>
        <div className="mb-1">
          <span className="block text-sm text-ink-mute font-medium">/ 100 final score</span>
          <span className="block font-mono text-xs text-primary font-semibold">72 → 91</span>
        </div>
      </div>

      <div className="grid grid-cols-2 gap-2.5 mb-5">
        {SUBSCORES.map(({ label, value }) => (
          <div key={label} className="bg-surface-2 border border-line rounded-lg px-3 py-2.5">
            <div className="flex items-baseline justify-between mb-1.5">
              <span className="text-[10px] font-semibold uppercase tracking-wider text-ink-faint">{label}</span>
              <span className="font-mono text-sm font-bold text-ink">{value}</span>
            </div>
            <div className="h-1 bg-line rounded-full overflow-hidden">
              <div className="h-full bg-primary rounded-full" style={{ width: `${value}%` }} />
            </div>
          </div>
        ))}
      </div>

      <div className="flex items-center">
        {STAGES.map((s, i) => (
          <div key={s} className={i < STAGES.length - 1 ? 'flex items-center flex-1' : 'flex items-center'}>
            <div className="flex flex-col items-center">
              <div className="w-5 h-5 rounded-full bg-primary flex items-center justify-center">
                <Check className="w-2.5 h-2.5 text-white dark:text-surface" strokeWidth={3} />
              </div>
              <span className="font-mono text-[8px] uppercase tracking-wide text-ink-faint mt-1">{s}</span>
            </div>
            {i < STAGES.length - 1 && <div className="h-px flex-1 mx-1 bg-primary/70 mb-4" />}
          </div>
        ))}
      </div>
    </div>
  );
}

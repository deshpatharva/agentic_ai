import { Download, Check, AlertCircle } from 'lucide-react';
import { useCountUp } from '../motion';
import { buildDownloadUrl } from '../api/client';

const SUBSCORES = [
  { key: 'ats',           label: 'ATS Match' },
  { key: 'impact',        label: 'Impact' },
  { key: 'skills_gap',    label: 'Skills Gap' },
  { key: 'readability',   label: 'Readability' },
  { key: 'jd_tailoring',  label: 'JD Tailoring' },
];

function SubScore({ label, value, delay }) {
  return (
    <div className="reveal bg-surface-2/60 border border-line rounded-lg px-3 py-2.5" style={{ animationDelay: `${delay}ms` }}>
      <div className="flex items-baseline justify-between mb-1.5">
        <span className="text-[10px] font-semibold uppercase tracking-wider text-ink-faint">{label}</span>
        <span className="text-sm font-mono font-bold text-ink">{value}</span>
      </div>
      <div className="h-1 bg-line/60 rounded-full overflow-hidden">
        <div
          className="h-full bg-primary rounded-full"
          style={{ width: `${value}%`, transition: 'width 800ms cubic-bezier(.22,1,.36,1)', transitionDelay: `${delay + 200}ms` }}
        />
      </div>
    </div>
  );
}

/**
 * Staged result reveal: serif count-up of the final score, staggered
 * sub-score cards, then the download CTA. Count-up and stagger collapse
 * to instant under prefers-reduced-motion.
 */
export default function ScoreReveal({ finalScore = 0, scores = null, iterations = 0, downloadUrl, report = null }) {
  const displayed = useCountUp(Math.round(finalScore));

  const baseline = report?.baseline_score;
  const improved = typeof baseline === 'number' && Math.round(finalScore) > baseline;
  const gapsAddressed = report?.gaps_addressed || [];
  const gapsRemaining = report?.gaps_remaining || [];

  return (
    <div className="my-5 max-w-md bg-card border border-line rounded-card shadow-lifted px-6 py-6">
      <p className="reveal text-xs font-semibold uppercase tracking-widest text-ink-faint mb-3">Optimization complete</p>

      <div className="reveal reveal-1 flex items-end gap-3 mb-5">
        <span className="font-display text-6xl font-semibold text-primary leading-none">{displayed}</span>
        <div className="mb-1">
          <span className="block text-sm text-ink-mute font-medium">/ 100 final score</span>
          <span className="block text-xs text-ink-faint">
            {improved && <span className="font-mono text-primary font-semibold">{baseline} → {Math.round(finalScore)} · </span>}
            {iterations > 0 && `${iterations} iteration${iterations !== 1 ? 's' : ''}`}
          </span>
        </div>
      </div>

      {scores && (
        <div className="grid grid-cols-2 gap-2.5 mb-5">
          {SUBSCORES.map((s, i) => (
            <SubScore key={s.key} label={s.label} value={Math.round(scores[s.key] ?? 0)} delay={250 + i * 120} />
          ))}
        </div>
      )}

      {(gapsAddressed.length > 0 || gapsRemaining.length > 0) && (
        <div className="reveal reveal-3 mb-5 rounded-lg bg-surface-2/50 border border-line px-3.5 py-3">
          <p className="text-[10px] font-semibold uppercase tracking-wider text-ink-faint mb-2">What changed</p>
          {gapsAddressed.length > 0 && (
            <p className="flex items-start gap-1.5 text-xs text-ink mb-1">
              <Check className="w-3.5 h-3.5 text-primary shrink-0 mt-0.5" strokeWidth={2.5} />
              <span><span className="text-ink-mute">Gaps woven in:</span> {gapsAddressed.join(', ')}</span>
            </p>
          )}
          {gapsRemaining.length > 0 && (
            <p className="flex items-start gap-1.5 text-xs text-ink-faint">
              <AlertCircle className="w-3.5 h-3.5 text-hilite shrink-0 mt-0.5" strokeWidth={2} />
              <span><span className="text-ink-mute">Not yet evidenced:</span> {gapsRemaining.join(', ')}</span>
            </p>
          )}
        </div>
      )}

      {downloadUrl && (
        <a
          href={buildDownloadUrl(downloadUrl)}
          download
          className="reveal reveal-4 flex items-center justify-center gap-2 w-full bg-primary hover:bg-primary-dark text-white dark:text-surface py-3 rounded-lg font-semibold shadow-primary transition-colors active:scale-[0.98]"
        >
          <Download className="w-4 h-4" /> Download Optimized Resume
        </a>
      )}
    </div>
  );
}

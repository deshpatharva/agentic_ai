import { clsx } from 'clsx';
import { Sparkles, FileText, ArrowRight } from 'lucide-react';

function matchTone(pct) {
  if (pct >= 70) return 'text-primary';
  if (pct >= 40) return 'text-hilite';
  return 'text-ink-faint';
}

export default function ProfilePicker({ profiles, onSelect, disabled = false }) {
  if (!profiles?.length) return null;

  return (
    <div className="ml-9 mb-5 max-w-lg">
      {/* Editorial divider label */}
      <div className="flex items-center gap-2.5 mb-3">
        <span className="h-px flex-1 bg-line" />
        <span className="text-[10px] font-semibold uppercase tracking-[0.2em] text-ink-faint">
          Choose a profile
        </span>
        <span className="h-px flex-1 bg-line" />
      </div>

      <div className="grid gap-2.5 sm:grid-cols-2">
        {profiles.map((p, i) => (
          <button
            key={p.id}
            disabled={disabled}
            onClick={() => onSelect(p)}
            style={{ animationDelay: `${i * 70}ms` }}
            className={clsx(
              'reveal group relative text-left rounded-card border px-4 pt-4 pb-3.5 transition-all duration-200 active:scale-[0.98]',
              disabled
                ? 'border-line bg-surface-2 opacity-60 cursor-not-allowed'
                : p.recommended
                ? 'border-primary/45 bg-accent-soft hover:border-primary hover:shadow-primary'
                : 'border-line bg-card hover:border-primary/40 hover:bg-surface-2 hover:shadow-card'
            )}
          >
            {p.recommended && (
              <span className="absolute -top-2.5 left-3.5 inline-flex items-center gap-1 rounded-full bg-primary px-2 py-0.5 text-[9px] font-bold uppercase tracking-[0.12em] text-white dark:text-ink shadow-sm">
                <Sparkles className="w-2.5 h-2.5" /> Recommended
              </span>
            )}

            <div className="flex items-center justify-between gap-2 mb-0.5">
              <div className="flex items-center gap-2 min-w-0">
                <FileText
                  className={clsx('w-4 h-4 shrink-0', p.recommended ? 'text-primary' : 'text-ink-faint')}
                  strokeWidth={1.75}
                />
                <span className="font-medium text-sm text-ink truncate">{p.label}</span>
              </div>
              {p.match_pct != null && (
                <span className={clsx('shrink-0 font-mono text-xs font-bold tabular-nums', matchTone(p.match_pct))}>
                  {p.match_pct}%
                </span>
              )}
            </div>

            {p.match_pct != null ? (
              <div className="mt-2 h-1 rounded-full bg-line/70 overflow-hidden">
                <div
                  className="h-full rounded-full bg-primary"
                  style={{ width: `${p.match_pct}%`, transition: 'width 700ms cubic-bezier(.22,1,.36,1)' }}
                />
              </div>
            ) : (
              <span className="mt-1 inline-flex items-center gap-1 text-[11px] text-ink-faint opacity-0 group-hover:opacity-100 transition-opacity">
                Tailor this <ArrowRight className="w-3 h-3" />
              </span>
            )}
          </button>
        ))}
      </div>
    </div>
  );
}

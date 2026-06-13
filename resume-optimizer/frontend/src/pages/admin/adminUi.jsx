import { clsx } from 'clsx';

/* Shared admin primitives. Admin renders inside a `.dark` scope, so token
   classes resolve to the ink palette; charts need literal colors (SVG). */

export const CHART = {
  green:   '#4DB892',
  amber:   '#D9A03F',
  red:     '#E06D61',
  neutral: '#7E766A',
  grid:    '#3C342A',
  tick:    { fontSize: 10, fill: '#7E766A' },
  tooltip: {
    background: '#1E1A15',
    border: '1px solid #3C342A',
    borderRadius: 8,
    color: '#EDE6DA',
    fontSize: 12,
  },
};

export function StatCard({ label, value, icon: Icon, accent = 'text-primary bg-accent-soft', sub }) {
  return (
    <div className="bg-card border border-line rounded-card p-5">
      <div className="flex items-center justify-between">
        <div className="min-w-0">
          <p className="text-xs text-ink-faint uppercase tracking-wide truncate">{label}</p>
          <p className="text-2xl font-bold font-mono text-ink mt-1">
            {value ?? <span className="text-ink-faint">—</span>}
          </p>
          {sub && <p className="text-[11px] text-ink-faint mt-0.5">{sub}</p>}
        </div>
        {Icon && (
          <div className={clsx('w-10 h-10 rounded-lg flex items-center justify-center shrink-0', accent)}>
            <Icon className="w-5 h-5" />
          </div>
        )}
      </div>
    </div>
  );
}

const STATUS_STYLES = {
  done:    'bg-accent-soft text-primary',
  running: 'bg-hilite-soft text-hilite',
  pending: 'bg-surface-2 text-ink-mute',
  error:   'bg-err-soft text-err',
};

export function RunStatusBadge({ status }) {
  return (
    <span className={clsx(
      'inline-flex items-center px-2 py-0.5 rounded-full text-xs font-semibold',
      STATUS_STYLES[status] || STATUS_STYLES.pending
    )}>
      {status}
    </span>
  );
}

export function ChartCard({ title, children, className }) {
  return (
    <div className={clsx('bg-card border border-line rounded-card p-5', className)}>
      <h3 className="text-sm font-semibold text-ink mb-4">{title}</h3>
      {children}
    </div>
  );
}

export function ChartState({ isLoading, error, empty, children }) {
  if (isLoading) return <div className="h-[260px] flex items-center justify-center text-ink-faint text-sm">Loading…</div>;
  if (error)     return <div className="h-[260px] flex items-center justify-center text-err text-sm">Error: {String(error)}</div>;
  if (empty)     return <div className="h-[260px] flex items-center justify-center text-ink-faint text-sm">No data for this period</div>;
  return children;
}

export function formatUsd(cents) {
  return `$${(cents / 100).toFixed(2)}`;
}

export function formatDuration(s) {
  if (s == null) return '—';
  if (s < 60) return `${s}s`;
  return `${Math.floor(s / 60)}m ${s % 60}s`;
}

import { clsx } from 'clsx';

function matchColor(pct) {
  if (pct >= 75) return 'green';
  if (pct >= 50) return 'amber';
  return 'gray';
}

export default function ProfileMatchCard({ profile, selected, onSelect }) {
  const { label, match_pct = 0, skills = [], reason } = profile;
  const color = matchColor(match_pct);

  const badgeClasses = {
    green: 'bg-accent-soft text-primary',
    amber: 'bg-hilite-soft text-hilite',
    gray: 'bg-surface-2 text-ink-mute',
  }[color];

  const barClasses = {
    green: 'bg-primary',
    amber: 'bg-hilite',
    gray: 'bg-ink-faint',
  }[color];

  return (
    <button
      type="button"
      onClick={() => onSelect(profile)}
      className={clsx(
        'w-full text-left rounded-card border px-4 py-3 transition-colors',
        selected
          ? 'border-primary bg-primary/5'
          : 'border-line bg-card hover:border-primary/40'
      )}
    >
      <div className="flex items-center justify-between mb-2">
        <span className="font-semibold text-ink text-sm">{label}</span>
        <span className={clsx('text-xs font-medium font-mono px-2 py-0.5 rounded-full', badgeClasses)}>
          {match_pct}%
        </span>
      </div>

      <div className="w-full h-px bg-surface-2 rounded-full mb-2.5 overflow-hidden">
        <div
          className={clsx('h-full rounded-full transition-all', barClasses)}
          style={{ width: `${Math.min(100, Math.max(0, match_pct))}%` }}
        />
      </div>

      {skills.slice(0, 4).length > 0 && (
        <div className="flex flex-wrap gap-1 mb-2">
          {skills.slice(0, 4).map((skill) => (
            <span key={skill} className="bg-surface-2 text-ink-mute text-[10px] font-medium px-2 py-0.5 rounded-full">
              {skill}
            </span>
          ))}
        </div>
      )}

      {reason && <p className="text-xs text-ink-faint line-clamp-1">{reason}</p>}
    </button>
  );
}

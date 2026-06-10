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
    green: 'bg-green-100 text-green-700',
    amber: 'bg-amber-100 text-amber-700',
    gray: 'bg-gray-100 text-gray-500',
  }[color];

  const barClasses = {
    green: 'bg-green-500',
    amber: 'bg-amber-400',
    gray: 'bg-gray-400',
  }[color];

  return (
    <button
      type="button"
      onClick={() => onSelect(profile)}
      className={clsx(
        'w-full text-left rounded-xl border px-4 py-3 transition-colors',
        selected
          ? 'border-primary bg-primary/5'
          : 'border-gray-200 bg-white hover:border-primary/40'
      )}
    >
      <div className="flex items-center justify-between mb-2">
        <span className="font-semibold text-gray-900 text-sm">{label}</span>
        <span className={clsx('text-xs font-medium px-2 py-0.5 rounded-full', badgeClasses)}>
          {match_pct}%
        </span>
      </div>

      <div className="w-full h-px bg-gray-100 rounded-full mb-2.5 overflow-hidden">
        <div
          className={clsx('h-full rounded-full transition-all', barClasses)}
          style={{ width: `${Math.min(100, Math.max(0, match_pct))}%` }}
        />
      </div>

      {skills.slice(0, 4).length > 0 && (
        <div className="flex flex-wrap gap-1 mb-2">
          {skills.slice(0, 4).map((skill) => (
            <span key={skill} className="bg-gray-100 text-gray-600 text-[10px] font-medium px-2 py-0.5 rounded-full">
              {skill}
            </span>
          ))}
        </div>
      )}

      {reason && <p className="text-xs text-gray-400 line-clamp-1">{reason}</p>}
    </button>
  );
}

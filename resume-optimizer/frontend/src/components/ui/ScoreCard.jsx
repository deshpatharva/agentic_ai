import { clsx } from 'clsx';

function scoreColor(score) {
  if (score >= 85) return { text: 'text-green-600', bar: 'bg-green-500', bg: 'bg-green-50' };
  if (score >= 70) return { text: 'text-amber-600', bar: 'bg-amber-500', bg: 'bg-amber-50' };
  return { text: 'text-red-600', bar: 'bg-red-500', bg: 'bg-red-50' };
}

export default function ScoreCard({ label, score, items = [], itemLabel = '' }) {
  const colors = scoreColor(score);
  return (
    <div className={clsx('rounded-2xl p-5 border', colors.bg, 'border-gray-100')}>
      <div className="flex items-start justify-between mb-3">
        <span className="text-sm font-medium text-gray-600">{label}</span>
        <span className={clsx('text-3xl font-bold', colors.text)}>{score}</span>
      </div>
      <div className="w-full h-2 bg-gray-200 rounded-full mb-3">
        <div className={clsx('h-2 rounded-full transition-all', colors.bar)} style={{ width: `${score}%` }} />
      </div>
      {items.length > 0 && (
        <ul className="space-y-1">
          {items.slice(0, 3).map((item, i) => (
            <li key={i} className="text-xs text-gray-500 truncate">• {item}</li>
          ))}
        </ul>
      )}
    </div>
  );
}

import { clsx } from 'clsx';

export default function QuotaBar({ used, total, label }) {
  const pct = total > 0 ? Math.min((used / total) * 100, 100) : 0;
  const color = pct >= 90 ? 'bg-red-500' : pct >= 70 ? 'bg-amber-500' : 'bg-primary';
  return (
    <div>
      {label && <div className="flex justify-between text-xs text-gray-500 mb-1"><span>{label}</span><span>{used} / {total}</span></div>}
      <div className="w-full h-2 bg-gray-200 rounded-full">
        <div className={clsx('h-2 rounded-full transition-all', color)} style={{ width: `${pct}%` }} />
      </div>
    </div>
  );
}

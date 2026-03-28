import { clsx } from 'clsx';

export default function QuotaBar({ used, total, label }) {
  const pct = total > 0 ? Math.min((used / total) * 100, 100) : 0;

  return (
    <div>
      {label && (
        <div className="flex justify-between text-xs text-gray-500 mb-1">
          <span>{label}</span>
          <span>{used} / {total}</span>
        </div>
      )}
      <div className="w-full h-2 bg-gray-100 rounded-full overflow-hidden">
        <div
          className="h-2 rounded-full transition-[width] duration-500 ease-out"
          style={{
            width: `${pct}%`,
            background: 'linear-gradient(90deg, #7F77DD, #a78bfa)',
          }}
        />
      </div>
    </div>
  );
}

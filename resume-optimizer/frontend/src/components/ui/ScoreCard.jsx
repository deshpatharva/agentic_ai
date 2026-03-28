import { clsx } from 'clsx';
import { useState, useEffect } from 'react';

function statusBadge(score) {
  if (score >= 85) return { label: 'Good',  cls: 'bg-green-100 text-green-700' };
  if (score >= 70) return { label: 'Fair',  cls: 'bg-amber-100 text-amber-700' };
  return                  { label: 'Low',   cls: 'bg-red-100 text-red-700' };
}

export default function ScoreCard({ label, score, items = [] }) {
  const [width, setWidth] = useState(0);
  const badge = statusBadge(score);

  useEffect(() => {
    const id = requestAnimationFrame(() => setWidth(score));
    return () => cancelAnimationFrame(id);
  }, [score]);

  return (
    <div className="bg-white rounded-2xl border border-[#ebebeb] shadow-card p-4">
      <div className="flex items-start justify-between mb-1">
        <span className="text-[11px] font-semibold text-gray-500 tracking-wide uppercase">{label}</span>
        <span className={clsx('text-[11px] font-bold px-2 py-0.5 rounded-full', badge.cls)}>
          {badge.label}
        </span>
      </div>
      <div className="text-2xl font-extrabold text-gray-900 leading-none">{score}</div>
      <div className="text-[10px] text-gray-400 mt-0.5">/ 100</div>
      <div className="w-full h-1.5 bg-gray-100 rounded-full mt-3 overflow-hidden">
        <div
          className="h-1.5 rounded-full"
          style={{
            width: `${width}%`,
            background: 'linear-gradient(90deg, #7F77DD, #a78bfa)',
            transition: 'width 600ms cubic-bezier(.4,0,.2,1)',
          }}
        />
      </div>
      {items.length > 0 && (
        <ul className="mt-3 space-y-1">
          {items.slice(0, 3).map((item, i) => (
            <li key={i} className="text-xs text-gray-500 truncate">• {item}</li>
          ))}
        </ul>
      )}
    </div>
  );
}

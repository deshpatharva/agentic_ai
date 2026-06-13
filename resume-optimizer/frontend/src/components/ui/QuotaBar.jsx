export default function QuotaBar({ used, total, label }) {
  const pct = total > 0 ? Math.min((used / total) * 100, 100) : 0;

  return (
    <div>
      {label && (
        <div className="flex justify-between text-xs text-ink-mute mb-1">
          <span>{label}</span>
          <span className="font-mono">{used} / {total}</span>
        </div>
      )}
      <div className="w-full h-2 bg-surface-2 rounded-full overflow-hidden">
        <div
          className="h-2 rounded-full bg-primary transition-[width] duration-500 ease-out"
          style={{ width: `${pct}%` }}
        />
      </div>
    </div>
  );
}

const STATS = [
  { stat: '5',         label: 'scoring dimensions',     sub: 'ATS · Impact · Skills · Readability · JD fit' },
  { stat: 'Guarded',   label: 'never invents experience', sub: 'every claim checked against your history' },
  { stat: 'Iterative', label: 'refines until it peaks',  sub: 'loops until the score stops climbing' },
  { stat: '3',         label: 'job sources',            sub: 'Adzuna · RemoteOK · The Muse' },
];

export default function StatsRow() {
  return (
    <section className="border-y border-line bg-surface-2/40">
      <div className="max-w-5xl mx-auto px-6 py-10 grid grid-cols-2 lg:grid-cols-4 gap-8">
        {STATS.map(({ stat, label, sub }) => (
          <div key={label}>
            <div className="font-display text-2xl font-semibold text-ink mb-1">{stat}</div>
            <div className="text-sm font-medium text-ink-mute">{label}</div>
            <div className="text-xs text-ink-faint mt-1">{sub}</div>
          </div>
        ))}
      </div>
    </section>
  );
}

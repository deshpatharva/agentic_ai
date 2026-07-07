import { useEffect, useState } from 'react';
import {
  LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer,
} from 'recharts';
import client from '../../api/client';
import { ChartCard, ChartState, CHART } from './adminUi';

function fmtMs(ms) {
  if (ms == null) return '—';
  return ms >= 1000 ? `${(ms / 1000).toFixed(1)}s` : `${Math.round(ms)}ms`;
}

export default function Observability() {
  const [days, setDays] = useState(30);
  const [series, setSeries] = useState(null);
  const [latency, setLatency] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    setLoading(true);
    setError(null);
    Promise.allSettled([
      client.get('/admin/observability/series',  { params: { days } }).then(r => setSeries(r.data)),
      client.get('/admin/observability/latency', { params: { days: Math.min(days, 90) } }).then(r => setLatency(r.data)),
    ]).then((results) => {
      const failed = results.find(r => r.status === 'rejected');
      if (failed) setError(failed.reason?.response?.data?.detail || failed.reason?.message);
      setLoading(false);
    });
  }, [days]);

  return (
    <div className="p-4 sm:p-8 space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-bold text-ink">AI Observability</h1>
        <div className="flex gap-1">
          {[7, 30, 90].map(d => (
            <button
              key={d}
              onClick={() => setDays(d)}
              className={`px-3 py-1 rounded-lg text-xs font-semibold transition-colors ${
                days === d ? 'bg-accent-soft text-primary' : 'text-ink-mute hover:bg-surface-2'
              }`}
            >
              {d}d
            </button>
          ))}
        </div>
      </div>

      {error && (
        <div className="p-3 bg-err-soft border border-err/30 rounded-lg text-sm text-err">
          Failed to load: {String(error)}
        </div>
      )}

      <ChartCard title="Calls vs errors">
        <ChartState isLoading={loading} empty={!series?.series?.length}>
          <ResponsiveContainer width="100%" height={260}>
            <LineChart data={series?.series || []}>
              <CartesianGrid strokeDasharray="3 3" stroke={CHART.grid} />
              <XAxis dataKey="bucket" tick={CHART.tick} tickFormatter={b => b.slice(5)} />
              <YAxis tick={CHART.tick} allowDecimals={false} />
              <Tooltip contentStyle={CHART.tooltip} />
              <Legend wrapperStyle={{ fontSize: 12 }} />
              <Line type="monotone" dataKey="calls" stroke={CHART.neutral} name="Calls" dot={false} strokeWidth={2} />
              <Line type="monotone" dataKey="errors" stroke={CHART.red} name="Errors" dot={false} strokeWidth={2} />
            </LineChart>
          </ResponsiveContainer>
        </ChartState>
      </ChartCard>

      <ChartCard title="Latency percentiles by model">
        <ChartState isLoading={loading} empty={!latency?.models?.length}>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-xs text-ink-faint uppercase tracking-wide">
                  <th className="py-2 pr-4">Model</th>
                  <th className="py-2 pr-4 text-right">Calls</th>
                  <th className="py-2 pr-4 text-right">p50</th>
                  <th className="py-2 pr-4 text-right">p95</th>
                  <th className="py-2 pr-4 text-right">p99</th>
                  <th className="py-2 text-right">TTFT p95</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-line/60">
                {(latency?.models || []).map(m => (
                  <tr key={m.model}>
                    <td className="py-2 pr-4 font-mono text-xs text-ink">{m.model}</td>
                    <td className="py-2 pr-4 text-right font-mono text-xs text-ink-mute">{m.calls}</td>
                    <td className="py-2 pr-4 text-right font-mono text-xs text-ink">{fmtMs(m.latency_ms.p50)}</td>
                    <td className="py-2 pr-4 text-right font-mono text-xs text-ink">{fmtMs(m.latency_ms.p95)}</td>
                    <td className="py-2 pr-4 text-right font-mono text-xs text-ink">{fmtMs(m.latency_ms.p99)}</td>
                    <td className="py-2 text-right font-mono text-xs text-ink-mute">{fmtMs(m.ttft_ms.p95)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </ChartState>
      </ChartCard>
    </div>
  );
}

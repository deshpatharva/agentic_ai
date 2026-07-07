import { useEffect, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import {
  LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer,
} from 'recharts';
import client from '../../api/client';
import { ChartCard, ChartState, CHART, RunStatusBadge } from './adminUi';

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
  const [errors, setErrors] = useState(null);
  const [trace, setTrace] = useState(null);
  const [traceQuery, setTraceQuery] = useState('');
  const [traceError, setTraceError] = useState(null);
  const [searchParams] = useSearchParams();

  async function loadTrace(params) {
    setTraceError(null);
    setTrace(null);
    try {
      const r = await client.get('/admin/observability/trace', { params });
      setTrace(r.data);
    } catch (e) {
      setTraceError(e.response?.data?.detail || e.message);
    }
  }

  useEffect(() => {
    const jobId = searchParams.get('job_id');
    if (jobId) {
      setTraceQuery(jobId);
      loadTrace({ job_id: jobId });
    }
  }, [searchParams]);

  useEffect(() => {
    setLoading(true);
    setError(null);
    Promise.allSettled([
      client.get('/admin/observability/series',  { params: { days } }).then(r => setSeries(r.data)),
      client.get('/admin/observability/latency', { params: { days: Math.min(days, 90) } }).then(r => setLatency(r.data)),
      client.get('/admin/observability/errors', { params: { days: Math.min(days, 90) } }).then(r => setErrors(r.data)),
    ]).then((results) => {
      const failed = results.find(r => r.status === 'rejected');
      if (failed) setError(failed.reason?.response?.data?.detail || failed.reason?.message);
      setLoading(false);
    });
  }, [days]);

  function submitTrace(e) {
    e.preventDefault();
    const q = traceQuery.trim();
    if (!q) return;
    const isUuid = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(q);
    loadTrace(isUuid ? { job_id: q } : { trace_id: q });
  }

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

      <ChartCard title="Errors by type">
        <ChartState isLoading={loading} empty={!errors?.breakdown?.length}>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-xs text-ink-faint uppercase tracking-wide">
                  <th className="py-2 pr-4">Type</th>
                  <th className="py-2 pr-4">Model</th>
                  <th className="py-2 pr-4 text-right">Count</th>
                  <th className="py-2 pr-4 text-right">Code</th>
                  <th className="py-2 text-right">Last seen</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-line/60">
                {(errors?.breakdown || []).map((b, i) => (
                  <tr key={i}>
                    <td className="py-2 pr-4 text-err font-mono text-xs">{b.error_type}</td>
                    <td className="py-2 pr-4 font-mono text-xs text-ink-mute">{b.model}</td>
                    <td className="py-2 pr-4 text-right font-mono text-xs text-ink">{b.count}</td>
                    <td className="py-2 pr-4 text-right font-mono text-xs text-ink-mute">{b.sample_error_code || '—'}</td>
                    <td className="py-2 text-right text-xs text-ink-faint">{new Date(b.last_seen).toLocaleString()}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {(errors?.recent || []).length > 0 && (
            <div className="mt-4">
              <p className="text-xs text-ink-faint uppercase tracking-wide mb-2">Recent errors</p>
              <ul className="divide-y divide-line/60">
                {errors.recent.slice(0, 10).map((r, i) => (
                  <li key={i} className="py-2 flex items-center gap-3 text-xs">
                    <span className="text-ink-faint w-32 shrink-0">{new Date(r.created_at).toLocaleString()}</span>
                    <span className="text-err font-mono">{r.error_type}</span>
                    <span className="text-ink-mute font-mono truncate flex-1">{r.call_kind || '—'} · {r.model}</span>
                    {(r.job_id || r.trace_id) && (
                      <button
                        onClick={() => { const q = r.job_id || r.trace_id; setTraceQuery(q); loadTrace(r.job_id ? { job_id: q } : { trace_id: q }); }}
                        className="text-primary hover:underline shrink-0"
                      >
                        trace →
                      </button>
                    )}
                  </li>
                ))}
              </ul>
            </div>
          )}
        </ChartState>
      </ChartCard>

      <ChartCard title="Trace waterfall">
        <form onSubmit={submitTrace} className="flex gap-2 mb-4">
          <input
            value={traceQuery}
            onChange={e => setTraceQuery(e.target.value)}
            placeholder="Paste a job id (UUID) or trace id"
            className="flex-1 bg-surface-2 border border-line rounded-lg px-3 py-1.5 text-sm text-ink placeholder:text-ink-faint"
          />
          <button type="submit" className="px-4 py-1.5 rounded-lg text-xs font-semibold bg-accent-soft text-primary">
            Look up
          </button>
        </form>
        {traceError && <p className="text-sm text-err mb-2">{String(traceError)}</p>}
        {trace && (
          <div className="space-y-1.5">
            {trace.job && (
              <p className="text-xs text-ink-faint mb-2 flex items-center gap-2">
                Job: <RunStatusBadge status={trace.job.status} />
                {trace.job.error_message && <span className="text-err truncate">{trace.job.error_message}</span>}
              </p>
            )}
            {(() => {
              const total = Math.max(...trace.calls.map(c => c.offset_ms + (c.latency_ms || 0)), 1);
              return trace.calls.map((c, i) => (
                <div key={i} className="flex items-center gap-2 text-xs">
                  <span className="w-36 truncate text-ink-mute">{c.call_kind || 'call'}</span>
                  <div className="flex-1 relative h-4 bg-surface-2 rounded">
                    <div
                      className="absolute h-4 rounded"
                      style={{
                        left: `${(c.offset_ms / total) * 100}%`,
                        width: `${Math.max(((c.latency_ms || 0) / total) * 100, 0.5)}%`,
                        background: c.status === 'error' ? CHART.red : CHART.green,
                      }}
                      title={`${c.model} · ${fmtMs(c.latency_ms)} · $${(c.cost_usd || 0).toFixed(4)}${c.error_type ? ' · ' + c.error_type : ''}${c.finish_reason ? ' · ' + c.finish_reason : ''}`}
                    />
                  </div>
                  <span className="w-16 text-right font-mono text-ink-faint">{fmtMs(c.latency_ms)}</span>
                </div>
              ));
            })()}
          </div>
        )}
      </ChartCard>
    </div>
  );
}

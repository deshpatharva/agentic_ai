import { Fragment, useEffect, useState, useCallback } from 'react';
import { ChevronDown, ChevronUp, RefreshCw } from 'lucide-react';
import { clsx } from 'clsx';
import client from '../../api/client';
import { RunStatusBadge, formatDuration } from './adminUi';

const STATUS_FILTERS = ['', 'running', 'done', 'error', 'pending'];

/* Per-stage timeline computed from event timestamps (events expire after 24h). */
function RunEvents({ jobId }) {
  const [events, setEvents] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    client.get(`/admin/pipeline-runs/${jobId}/events`)
      .then(r => setEvents(r.data.events || []))
      .catch(e => setError(e.response?.data?.detail || e.message));
  }, [jobId]);

  if (error) return <p className="text-xs text-err px-4 py-3">Failed to load events: {String(error)}</p>;
  if (events === null) return <p className="text-xs text-ink-faint px-4 py-3">Loading timeline…</p>;
  if (!events.length) return <p className="text-xs text-ink-faint px-4 py-3">No events stored (expired after 24h).</p>;

  // Duration of each step = gap to the next event.
  const rows = events.map((ev, i) => {
    const next = events[i + 1];
    const dur = next ? Math.max(0, Math.round((new Date(next.at) - new Date(ev.at)) / 1000)) : null;
    return { ...ev, dur };
  });

  return (
    <div className="px-4 py-3 space-y-1 max-h-72 overflow-y-auto">
      {rows.map((ev, i) => (
        <div key={i} className="flex items-start gap-3 text-xs font-mono">
          <span className="text-ink-faint shrink-0 w-16">
            {new Date(ev.at).toLocaleTimeString([], { hour12: false })}
          </span>
          <span className={clsx(
            'shrink-0 w-20 font-semibold',
            ev.type === 'error' ? 'text-err' : ev.type === 'done' ? 'text-primary' : ev.type === 'average' ? 'text-hilite' : 'text-ink-mute'
          )}>
            {ev.type}
          </span>
          <span className="flex-1 text-ink-mute break-all">
            {ev.type === 'average'
              ? `score ${ev.score} (iter ${ev.iteration})`
              : ev.message || JSON.stringify(ev).slice(0, 140)}
          </span>
          {ev.dur != null && <span className="text-ink-faint shrink-0">+{ev.dur}s</span>}
        </div>
      ))}
    </div>
  );
}

export default function PipelineRuns() {
  const [runs, setRuns] = useState([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [status, setStatus] = useState('');
  const [loading, setLoading] = useState(true);
  const [expanded, setExpanded] = useState(null);
  const perPage = 20;

  const fetchRuns = useCallback(() => {
    setLoading(true);
    const params = { page, per_page: perPage };
    if (status) params.status = status;
    client.get('/admin/pipeline-runs', { params })
      .then(r => { setRuns(r.data.results || []); setTotal(r.data.total || 0); })
      .catch(() => { setRuns([]); setTotal(0); })
      .finally(() => setLoading(false));
  }, [page, status]);

  useEffect(() => { fetchRuns(); }, [fetchRuns]);

  const totalPages = Math.ceil(total / perPage);

  return (
    <div className="p-4 sm:p-8">
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-xl font-bold text-ink">
          Pipeline Runs <span className="text-ink-faint text-base font-normal">({total})</span>
        </h1>
        <button
          onClick={fetchRuns}
          className="flex items-center gap-1.5 px-3 py-1.5 text-xs text-ink-mute bg-card border border-line rounded-lg hover:bg-surface-2 transition-colors"
        >
          <RefreshCw className="w-3.5 h-3.5" /> Refresh
        </button>
      </div>

      {/* Status filter */}
      <div className="flex gap-2 mb-4">
        {STATUS_FILTERS.map(f => (
          <button key={f}
            onClick={() => { setStatus(f); setPage(1); setExpanded(null); }}
            className={clsx(
              'px-3 py-1.5 rounded-lg text-xs font-medium transition-colors',
              status === f
                ? 'bg-surface-2 text-ink'
                : 'text-ink-faint hover:text-ink-mute hover:bg-surface-2/60'
            )}
          >
            {f === '' ? 'All' : f}
          </button>
        ))}
      </div>

      <div className="bg-card border border-line rounded-card overflow-hidden">
        <div className="overflow-x-auto">
        <table className="w-full text-sm min-w-[920px]">
          <thead>
            <tr className="border-b border-line text-ink-faint text-xs uppercase tracking-wide">
              <th className="px-4 py-3 text-left">Status</th>
              <th className="px-4 py-3 text-left">User</th>
              <th className="px-4 py-3 text-left">File</th>
              <th className="px-4 py-3 text-right">Score</th>
              <th className="px-4 py-3 text-right">Iter</th>
              <th className="px-4 py-3 text-right">Cost</th>
              <th className="px-4 py-3 text-right">Tokens</th>
              <th className="px-4 py-3 text-right">Duration</th>
              <th className="px-4 py-3 text-left">Started</th>
              <th className="px-4 py-3 w-8" />
            </tr>
          </thead>
          <tbody>
            {loading ? (
              <tr><td colSpan={10} className="px-4 py-10 text-center text-ink-faint">Loading…</td></tr>
            ) : runs.length === 0 ? (
              <tr><td colSpan={10} className="px-4 py-10 text-center text-ink-faint">No runs found.</td></tr>
            ) : runs.map(r => (
              <Fragment key={r.id}>
                <tr
                  onClick={() => setExpanded(expanded === r.id ? null : r.id)}
                  className="border-b border-line/60 hover:bg-surface-2/60 cursor-pointer transition-colors"
                >
                  <td className="px-4 py-3"><RunStatusBadge status={r.status} /></td>
                  <td className="px-4 py-3 text-ink-mute truncate max-w-[180px]">{r.user_email || '—'}</td>
                  <td className="px-4 py-3 text-ink-faint truncate max-w-[140px]">{r.filename}</td>
                  <td className="px-4 py-3 text-right font-mono text-ink">{r.final_score ?? '—'}</td>
                  <td className="px-4 py-3 text-right font-mono text-ink-mute">{r.iterations}</td>
                  <td className="px-4 py-3 text-right font-mono text-ink-mute">{r.cost_usd != null ? `$${r.cost_usd.toFixed(3)}` : '—'}</td>
                  <td className="px-4 py-3 text-right font-mono text-ink-mute">{r.tokens != null ? r.tokens.toLocaleString() : '—'}</td>
                  <td className="px-4 py-3 text-right font-mono text-ink-mute">{formatDuration(r.duration_s)}</td>
                  <td className="px-4 py-3 text-ink-faint text-xs whitespace-nowrap">{new Date(r.created_at).toLocaleString()}</td>
                  <td className="px-4 py-3 text-ink-faint">
                    {expanded === r.id ? <ChevronUp className="w-4 h-4" /> : <ChevronDown className="w-4 h-4" />}
                  </td>
                </tr>
                {expanded === r.id && (
                  <tr className="border-b border-line/60 bg-surface-2/40">
                    <td colSpan={10} className="p-0">
                      {r.error_message && (
                        <p className="text-xs text-err font-mono px-4 pt-3 break-all">{r.error_message}</p>
                      )}
                      <RunEvents jobId={r.id} />
                    </td>
                  </tr>
                )}
              </Fragment>
            ))}
          </tbody>
        </table>
        </div>
      </div>

      {totalPages > 1 && (
        <div className="flex items-center justify-center gap-3 mt-5">
          <button
            disabled={page === 1}
            onClick={() => setPage(p => p - 1)}
            className="px-3 py-1.5 text-sm text-ink-mute bg-card border border-line rounded-lg disabled:opacity-40 hover:bg-surface-2 transition-colors"
          >
            Prev
          </button>
          <span className="text-sm text-ink-faint">Page {page} of {totalPages}</span>
          <button
            disabled={page === totalPages}
            onClick={() => setPage(p => p + 1)}
            className="px-3 py-1.5 text-sm text-ink-mute bg-card border border-line rounded-lg disabled:opacity-40 hover:bg-surface-2 transition-colors"
          >
            Next
          </button>
        </div>
      )}
    </div>
  );
}

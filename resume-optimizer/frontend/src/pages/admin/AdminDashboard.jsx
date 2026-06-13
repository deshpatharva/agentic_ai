import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { Users, Activity, FileText, Zap, AlertTriangle, DollarSign } from 'lucide-react';
import { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer } from 'recharts';
import client from '../../api/client';
import { StatCard, RunStatusBadge, ChartCard, ChartState, CHART, formatUsd, formatDuration } from './adminUi';

export default function AdminDashboard() {
  const [stats, setStats] = useState(null);
  const [statsError, setStatsError] = useState(null);
  const [health, setHealth] = useState([]);
  const [runs, setRuns] = useState([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    Promise.allSettled([
      client.get('/admin/stats').then(r => setStats(r.data)),
      client.get('/admin/analytics', { params: { days: 14 } }).then(r => setHealth(r.data.pipeline_health || [])),
      client.get('/admin/pipeline-runs', { params: { per_page: 8 } }).then(r => setRuns(r.data.results || [])),
    ]).then((results) => {
      const failed = results.find(r => r.status === 'rejected');
      if (failed) setStatsError(failed.reason?.response?.data?.detail || failed.reason?.message);
      setLoading(false);
    });
  }, []);

  const cards = [
    { label: 'Total Users',        value: stats?.total_users,                                   icon: Users,         accent: 'bg-accent-soft text-primary' },
    { label: 'Active Users',       value: stats?.active_users,                                  icon: Activity,      accent: 'bg-accent-soft text-primary' },
    { label: 'Runs Today',         value: stats?.pipeline_runs_today,                           icon: Zap,           accent: 'bg-accent-soft text-primary' },
    { label: 'Resumes Stored',     value: stats?.total_resumes,                                 icon: FileText,      accent: 'bg-surface-2 text-ink-mute' },
    {
      label: 'Stuck Jobs',
      value: stats?.stuck_jobs,
      icon: AlertTriangle,
      accent: stats?.stuck_jobs > 0 ? 'bg-err-soft text-err' : 'bg-surface-2 text-ink-mute',
    },
    {
      label: 'Spend Today',
      value: stats != null ? formatUsd(stats.total_cost_cents_today) : null,
      sub: stats != null ? `${formatUsd(stats.total_cost_cents_month)} this month · ~$${stats.avg_cost_per_run}/run` : null,
      icon: DollarSign,
      accent: 'bg-hilite-soft text-hilite',
    },
  ];

  return (
    <div className="p-4 sm:p-8">
      <h1 className="text-xl font-bold text-ink mb-6">Overview</h1>

      {statsError && (
        <div className="mb-4 p-3 bg-err-soft border border-err/30 rounded-lg text-sm text-err">
          Failed to load some metrics: {String(statsError)}
        </div>
      )}

      {loading ? (
        <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-3 gap-4 mb-6">
          {[...Array(6)].map((_, i) => (
            <div key={i} className="h-24 bg-card border border-line rounded-card animate-pulse" />
          ))}
        </div>
      ) : (
        <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-3 gap-4 mb-6">
          {cards.map(c => <StatCard key={c.label} {...c} />)}
        </div>
      )}

      <div className="grid grid-cols-1 xl:grid-cols-2 gap-6">
        {/* Pipeline health — last 14 days */}
        <ChartCard title="Pipeline health — last 14 days">
          <ChartState isLoading={loading} empty={!health.length}>
            <ResponsiveContainer width="100%" height={260}>
              <LineChart data={health}>
                <CartesianGrid strokeDasharray="3 3" stroke={CHART.grid} />
                <XAxis dataKey="date" tick={CHART.tick} tickFormatter={d => d.slice(5)} />
                <YAxis tick={CHART.tick} allowDecimals={false} />
                <Tooltip contentStyle={CHART.tooltip} />
                <Legend wrapperStyle={{ fontSize: 12 }} />
                <Line type="monotone" dataKey="successful" stroke={CHART.green} name="Successful" dot={false} strokeWidth={2} />
                <Line type="monotone" dataKey="failed" stroke={CHART.red} name="Failed" dot={false} strokeWidth={2} />
              </LineChart>
            </ResponsiveContainer>
          </ChartState>
        </ChartCard>

        {/* Recent runs feed */}
        <div className="bg-card border border-line rounded-card p-5">
          <div className="flex items-center justify-between mb-4">
            <h3 className="text-sm font-semibold text-ink">Recent runs</h3>
            <Link to="/admin/runs" className="text-xs text-primary hover:underline">View all →</Link>
          </div>
          {loading ? (
            <div className="h-[260px] flex items-center justify-center text-ink-faint text-sm">Loading…</div>
          ) : runs.length === 0 ? (
            <div className="h-[260px] flex items-center justify-center text-ink-faint text-sm">No runs yet</div>
          ) : (
            <ul className="divide-y divide-line/60">
              {runs.map(r => (
                <li key={r.id} className="py-2.5 flex items-center gap-3 text-sm">
                  <RunStatusBadge status={r.status} />
                  <span className="flex-1 truncate text-ink-mute">{r.user_email || 'unknown'}</span>
                  <span className="font-mono text-xs text-ink">{r.final_score ?? '—'}</span>
                  <span className="font-mono text-xs text-ink-faint w-14 text-right">{formatDuration(r.duration_s)}</span>
                  <span className="text-xs text-ink-faint w-20 text-right">
                    {new Date(r.created_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
                  </span>
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>
    </div>
  );
}

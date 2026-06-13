import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { AreaChart, Area, XAxis, YAxis, Tooltip, ResponsiveContainer } from 'recharts';
import { FileText, Target, Briefcase, TrendingUp, Download } from 'lucide-react';
import AppShell from '../components/layout/AppShell';
import Card from '../components/ui/Card';
import QuotaBar from '../components/ui/QuotaBar';
import Badge from '../components/ui/Badge';
import client, { buildDownloadUrl } from '../api/client';
import useAuthStore from '../store/authStore';
import OnboardingBanner from '../components/OnboardingBanner';

function scoreColor(s) {
  if (s >= 85) return 'text-primary bg-accent-soft';
  if (s >= 70) return 'text-hilite bg-hilite-soft';
  return 'text-err bg-err-soft';
}

export default function Dashboard() {
  const { user } = useAuthStore();
  const [summary, setSummary] = useState(null);
  const [usage, setUsage] = useState([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState(null);
  const [chartDays, setChartDays] = useState(30);

  useEffect(() => {
    client.get('/dashboard/summary')
      .then(r => setSummary(r.data))
      .catch(err => setLoadError(err.response?.data?.detail || 'Could not load your dashboard.'))
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    client.get('/dashboard/usage-history', { params: { days: chartDays } })
      .then(r => setUsage(r.data.rows || []))
      .catch(() => setUsage([]));
  }, [chartDays]);

  const hour = new Date().getHours();
  const greeting = hour < 12 ? 'Good morning' : hour < 17 ? 'Good afternoon' : 'Good evening';
  const name = user?.full_name?.split(' ')[0] || user?.email?.split('@')[0] || 'there';

  if (loading) return (
    <AppShell><div className="h-full flex items-center justify-center text-ink-faint">Loading…</div></AppShell>
  );

  const stats = summary?.stats || {};
  const today = summary?.today || {};
  const limits = summary?.limits || {};

  return (
    <AppShell>
      <div className="page-fade">
        <div className="max-w-5xl mx-auto px-4 sm:px-8 py-8">
          <h1 className="font-display text-2xl font-semibold text-ink mb-1">{greeting}, {name} 👋</h1>
          <p className="text-ink-mute mb-6">Here's your resume optimization overview.</p>

          {loadError && (
            <div className="mb-6 p-3 bg-err-soft border border-err/30 rounded-lg text-sm text-err">
              {String(loadError)} <button onClick={() => window.location.reload()} className="underline ml-1">Retry</button>
            </div>
          )}

          <OnboardingBanner />

          {/* Stats row */}
          <div className="grid grid-cols-2 lg:grid-cols-4 gap-4 mb-8">
            {[
              { icon: TrendingUp, label: "Today's runs",      value: `${today.runs || 0} / ${limits.daily_uploads || 0}`, iconBg: 'bg-accent-soft', iconColor: 'text-primary' },
              { icon: Target,     label: 'Best score',        value: stats.best_score || 0,                                iconBg: 'bg-accent-soft', iconColor: 'text-primary' },
              { icon: FileText,   label: 'Resumes optimized', value: stats.total_resumes || 0,                             iconBg: 'bg-accent-soft', iconColor: 'text-primary' },
              { icon: Briefcase,  label: 'Unread matches',    value: stats.unread_matches || 0,                            iconBg: 'bg-hilite-soft', iconColor: 'text-hilite' },
            ].map(({ icon: Icon, label, value, iconBg, iconColor }) => (
              <Card key={label} className="!p-5">
                <div className={`w-9 h-9 rounded-lg flex items-center justify-center mb-3 ${iconBg}`}>
                  <Icon className={`w-4 h-4 ${iconColor}`} />
                </div>
                <div className="text-2xl font-bold font-mono text-ink mb-0.5">{value}</div>
                <div className="text-xs text-ink-mute">{label}</div>
              </Card>
            ))}
          </div>

          <div className="grid grid-cols-1 lg:grid-cols-3 gap-6 mb-8">
            {/* Usage chart */}
            <Card
              header={
                <>
                  <span className="font-bold text-sm text-ink">Usage — last {chartDays} days</span>
                  <select
                    value={chartDays}
                    onChange={(e) => setChartDays(parseInt(e.target.value))}
                    className="text-xs text-ink-mute bg-card border border-line rounded-lg px-2 py-1 focus:outline-none focus:border-primary"
                  >
                    <option value={7}>7 days</option>
                    <option value={30}>30 days</option>
                    <option value={90}>90 days</option>
                  </select>
                </>
              }
              className="lg:col-span-2"
            >
              {usage.some(r => r.pipeline_runs > 0) ? (
                <ResponsiveContainer width="100%" height={180}>
                  <AreaChart data={usage}>
                    <defs>
                      <linearGradient id="grad" x1="0" y1="0" x2="0" y2="1">
                        <stop offset="5%" stopColor="#2E9272" stopOpacity={0.3} />
                        <stop offset="95%" stopColor="#2E9272" stopOpacity={0} />
                      </linearGradient>
                    </defs>
                    <XAxis dataKey="date" tick={{ fontSize: 10, fill: '#8C857D' }} tickFormatter={d => d.slice(5)} />
                    <YAxis tick={{ fontSize: 10, fill: '#8C857D' }} allowDecimals={false} />
                    <Tooltip
                      labelFormatter={d => d}
                      formatter={v => [v, 'runs']}
                      contentStyle={{ background: 'rgb(var(--c-surface))', border: '1px solid rgb(var(--c-line))', borderRadius: 8, color: 'rgb(var(--c-ink))' }}
                    />
                    <Area type="monotone" dataKey="pipeline_runs" stroke="#2E9272" fill="url(#grad)" strokeWidth={2} />
                  </AreaChart>
                </ResponsiveContainer>
              ) : <p className="text-sm text-ink-faint text-center py-12">No usage data yet — run your first pipeline!</p>}
            </Card>

            {/* Quota */}
            <Card header="Daily quota">
              <QuotaBar used={today.runs || 0} total={limits.daily_uploads || 2} label="Pipeline runs" />
              <div className="mt-6 text-center">
                <Badge variant={user?.plan || 'free'} className="text-sm px-3 py-1">{user?.plan || 'free'}</Badge>
                {user?.plan === 'free' && (
                  <Link to="/dashboard/settings" className="block mt-4 text-sm text-primary hover:underline">Upgrade for more →</Link>
                )}
              </div>
            </Card>
          </div>

          {/* Recent resumes */}
          <Card header="Recent resumes">
            {summary?.recent_resumes?.length > 0 ? (
              <div className="overflow-x-auto">
              <table className="w-full text-sm min-w-[480px]">
                <thead><tr className="text-left text-xs text-ink-faint border-b border-line">
                  <th className="pb-3 font-medium">File</th>
                  <th className="pb-3 font-medium">Score</th>
                  <th className="pb-3 font-medium">Iterations</th>
                  <th className="pb-3 font-medium">Date</th>
                  <th className="pb-3 font-medium"></th>
                </tr></thead>
                <tbody className="divide-y divide-line/50">
                  {summary.recent_resumes.map(r => (
                    <tr key={r.id} className="hover:bg-surface-2 transition-colors">
                      <td className="py-3 font-medium text-ink truncate max-w-[180px]">{r.filename}</td>
                      <td className="py-3">
                        <span className={`inline-block px-2 py-0.5 rounded-full text-xs font-medium font-mono ${scoreColor(r.final_score || 0)}`}>
                          {r.final_score ? Math.round(r.final_score) : '—'}
                        </span>
                      </td>
                      <td className="py-3 text-ink-mute">{r.iterations}</td>
                      <td className="py-3 text-ink-faint text-xs">{new Date(r.created_at).toLocaleDateString()}</td>
                      <td className="py-3">
                        <a href={buildDownloadUrl(r.download_url)} className="flex items-center gap-1 text-primary hover:text-primary-dark text-xs font-medium">
                          <Download className="w-3 h-3" />Download
                        </a>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
              </div>
            ) : <p className="text-sm text-ink-faint">No resumes yet. <Link to="/optimize" className="text-primary hover:underline">Optimize your first resume →</Link></p>}
          </Card>
        </div>
      </div>
    </AppShell>
  );
}

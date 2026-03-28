import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { AreaChart, Area, XAxis, YAxis, Tooltip, ResponsiveContainer } from 'recharts';
import { FileText, Target, Briefcase, TrendingUp, Download } from 'lucide-react';
import Sidebar from '../components/layout/Sidebar';
import Card from '../components/ui/Card';
import QuotaBar from '../components/ui/QuotaBar';
import Badge from '../components/ui/Badge';
import client from '../api/client';
import useAuthStore from '../store/authStore';

function scoreColor(s) {
  if (s >= 85) return 'text-green-600 bg-green-50';
  if (s >= 70) return 'text-amber-600 bg-amber-50';
  return 'text-red-600 bg-red-50';
}

export default function Dashboard() {
  const { user } = useAuthStore();
  const [summary, setSummary] = useState(null);
  const [usage, setUsage] = useState([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    Promise.all([
      client.get('/dashboard/summary').then(r => setSummary(r.data)),
      client.get('/dashboard/usage-history').then(r => setUsage(r.data.rows || [])),
    ]).finally(() => setLoading(false));
  }, []);

  const hour = new Date().getHours();
  const greeting = hour < 12 ? 'Good morning' : hour < 17 ? 'Good afternoon' : 'Good evening';
  const name = user?.full_name?.split(' ')[0] || user?.email?.split('@')[0] || 'there';

  if (loading) return (
    <div className="flex h-screen"><Sidebar /><div className="flex-1 flex items-center justify-center text-gray-400">Loading…</div></div>
  );

  const stats = summary?.stats || {};
  const today = summary?.today || {};
  const limits = summary?.limits || {};

  return (
    <div className="flex h-screen bg-surface overflow-hidden page-fade">
      <Sidebar />
      <main className="flex-1 overflow-y-auto">
        <div className="max-w-5xl mx-auto px-8 py-8">
          <h1 className="text-2xl font-bold text-gray-900 mb-1">{greeting}, {name} 👋</h1>
          <p className="text-gray-500 mb-8">Here's your resume optimization overview.</p>

          {/* Stats row */}
          <div className="grid grid-cols-2 lg:grid-cols-4 gap-4 mb-8">
            {[
              { icon: TrendingUp, label: "Today's runs",      value: `${today.runs || 0} / ${limits.daily_uploads || 0}`, iconBg: 'bg-violet-50', iconColor: 'text-violet-500' },
              { icon: Target,     label: 'Best score',        value: stats.best_score || 0,                                iconBg: 'bg-green-50',  iconColor: 'text-green-500' },
              { icon: FileText,   label: 'Resumes optimized', value: stats.total_resumes || 0,                             iconBg: 'bg-violet-50', iconColor: 'text-violet-500' },
              { icon: Briefcase,  label: 'Unread matches',    value: stats.unread_matches || 0,                            iconBg: 'bg-amber-50',  iconColor: 'text-amber-500' },
            ].map(({ icon: Icon, label, value, iconBg, iconColor }) => (
              <Card key={label} className="!p-5">
                <div className={`w-9 h-9 rounded-xl flex items-center justify-center mb-3 ${iconBg}`}>
                  <Icon className={`w-4 h-4 ${iconColor}`} />
                </div>
                <div className="text-2xl font-bold text-gray-900 mb-0.5">{value}</div>
                <div className="text-xs text-gray-500">{label}</div>
              </Card>
            ))}
          </div>

          <div className="grid grid-cols-1 lg:grid-cols-3 gap-6 mb-8">
            {/* Usage chart */}
            <Card header="Usage — last 30 days" className="lg:col-span-2">
              {usage.length > 0 ? (
                <ResponsiveContainer width="100%" height={180}>
                  <AreaChart data={usage}>
                    <defs>
                      <linearGradient id="grad" x1="0" y1="0" x2="0" y2="1">
                        <stop offset="5%" stopColor="#7F77DD" stopOpacity={0.3} />
                        <stop offset="95%" stopColor="#7F77DD" stopOpacity={0} />
                      </linearGradient>
                    </defs>
                    <XAxis dataKey="date" tick={{ fontSize: 10 }} tickFormatter={d => d.slice(5)} />
                    <YAxis tick={{ fontSize: 10 }} allowDecimals={false} />
                    <Tooltip labelFormatter={d => d} formatter={v => [v, 'runs']} />
                    <Area type="monotone" dataKey="pipeline_runs" stroke="#7F77DD" fill="url(#grad)" strokeWidth={2} />
                  </AreaChart>
                </ResponsiveContainer>
              ) : <p className="text-sm text-gray-400 text-center py-12">No usage data yet — run your first pipeline!</p>}
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
              <table className="w-full text-sm">
                <thead><tr className="text-left text-xs text-gray-400 border-b border-gray-100">
                  <th className="pb-3 font-medium">File</th>
                  <th className="pb-3 font-medium">Score</th>
                  <th className="pb-3 font-medium">Iterations</th>
                  <th className="pb-3 font-medium">Date</th>
                  <th className="pb-3 font-medium"></th>
                </tr></thead>
                <tbody className="divide-y divide-gray-50">
                  {summary.recent_resumes.map(r => (
                    <tr key={r.id} className="hover:bg-gray-50 transition-colors">
                      <td className="py-3 font-medium text-gray-800 truncate max-w-[180px]">{r.filename}</td>
                      <td className="py-3">
                        <span className={`inline-block px-2 py-0.5 rounded-full text-xs font-medium ${scoreColor(r.final_score || 0)}`}>
                          {r.final_score ? Math.round(r.final_score) : '—'}
                        </span>
                      </td>
                      <td className="py-3 text-gray-500">{r.iterations}</td>
                      <td className="py-3 text-gray-400 text-xs">{new Date(r.created_at).toLocaleDateString()}</td>
                      <td className="py-3">
                        <a href={r.download_url} download className="flex items-center gap-1 text-primary hover:text-primary-dark text-xs font-medium">
                          <Download className="w-3 h-3" />Download
                        </a>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            ) : <p className="text-sm text-gray-400">No resumes yet. <Link to="/app" className="text-primary hover:underline">Optimize your first resume →</Link></p>}
          </Card>
        </div>
      </main>
    </div>
  );
}

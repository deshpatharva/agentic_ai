import { useEffect, useState } from 'react';
import {
  LineChart, Line, AreaChart, Area, BarChart, Bar, PieChart, Pie, Cell,
  XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer,
} from 'recharts';
import client from '../../api/client';
import { ChartCard, ChartState, CHART } from './adminUi';

const PIE_COLORS = [CHART.neutral, CHART.green, CHART.amber];

export default function Analytics() {
  const [analytics, setAnalytics] = useState(null);
  const [providers, setProviders] = useState([]);
  const [days, setDays] = useState(30);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    setLoading(true);
    setError(null);
    Promise.allSettled([
      client.get('/admin/analytics', { params: { days } }).then(r => setAnalytics(r.data)),
      client.get('/admin/provider-costs').then(r => setProviders(r.data.providers || [])),
    ]).then((results) => {
      const failed = results[0].status === 'rejected' ? results[0] : null;
      if (failed) setError(failed.reason?.response?.data?.detail || failed.reason?.message);
      setLoading(false);
    });
  }, [days]);

  const planData = analytics ? [
    { name: 'Free',       value: analytics.plan_distribution?.free || 0 },
    { name: 'Pro',        value: analytics.plan_distribution?.pro || 0 },
    { name: 'Enterprise', value: analytics.plan_distribution?.enterprise || 0 },
  ] : [];
  const planEmpty = planData.every(d => d.value === 0);

  const costData = (analytics?.daily_costs || []).map(d => ({
    ...d,
    cost_usd: +(d.cost_cents / 100).toFixed(2),
  }));

  const sourceData = Object.entries(analytics?.source_counts || {}).map(([source, count]) => ({ source, count }));

  return (
    <div className="p-4 sm:p-8">
      <div className="flex justify-between items-center mb-8">
        <h1 className="text-xl font-bold text-ink">Analytics</h1>
        <select
          value={days}
          onChange={(e) => setDays(parseInt(e.target.value))}
          className="px-4 py-2 bg-card border border-line text-ink rounded-lg text-sm focus:outline-none focus:border-primary"
        >
          <option value={7}>Last 7 days</option>
          <option value={30}>Last 30 days</option>
          <option value={90}>Last 90 days</option>
        </select>
      </div>

      <div className="grid grid-cols-1 xl:grid-cols-2 gap-6 mb-6">
        <ChartCard title="User growth">
          <ChartState isLoading={loading} error={error} empty={!analytics?.user_growth?.length}>
            <ResponsiveContainer width="100%" height={260}>
              <LineChart data={analytics?.user_growth}>
                <CartesianGrid strokeDasharray="3 3" stroke={CHART.grid} />
                <XAxis dataKey="date" tick={CHART.tick} tickFormatter={d => d.slice(5)} />
                <YAxis tick={CHART.tick} allowDecimals={false} />
                <Tooltip contentStyle={CHART.tooltip} />
                <Legend wrapperStyle={{ fontSize: 12 }} />
                <Line type="monotone" dataKey="cumulative_users" stroke={CHART.green} name="Cumulative" dot={false} strokeWidth={2} />
                <Line type="monotone" dataKey="daily_signups" stroke={CHART.amber} name="Daily signups" dot={false} strokeWidth={2} />
              </LineChart>
            </ResponsiveContainer>
          </ChartState>
        </ChartCard>

        <ChartCard title="Plan distribution">
          <ChartState isLoading={loading} error={error} empty={planEmpty}>
            <ResponsiveContainer width="100%" height={260}>
              <PieChart>
                <Pie
                  data={planData}
                  cx="50%" cy="50%"
                  labelLine={false}
                  label={({ name, value }) => `${name}: ${value}`}
                  outerRadius={85}
                  dataKey="value"
                  stroke="none"
                >
                  {planData.map((entry, i) => <Cell key={entry.name} fill={PIE_COLORS[i]} />)}
                </Pie>
                <Tooltip contentStyle={CHART.tooltip} />
              </PieChart>
            </ResponsiveContainer>
          </ChartState>
        </ChartCard>
      </div>

      <div className="grid grid-cols-1 xl:grid-cols-2 gap-6 mb-6">
        <ChartCard title="LLM spend per day (USD)">
          <ChartState isLoading={loading} error={error} empty={!costData.length}>
            <ResponsiveContainer width="100%" height={260}>
              <AreaChart data={costData}>
                <defs>
                  <linearGradient id="costGrad" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%" stopColor={CHART.amber} stopOpacity={0.3} />
                    <stop offset="95%" stopColor={CHART.amber} stopOpacity={0} />
                  </linearGradient>
                </defs>
                <CartesianGrid strokeDasharray="3 3" stroke={CHART.grid} />
                <XAxis dataKey="date" tick={CHART.tick} tickFormatter={d => d.slice(5)} />
                <YAxis tick={CHART.tick} tickFormatter={v => `$${v}`} />
                <Tooltip contentStyle={CHART.tooltip} formatter={(v) => [`$${v}`, 'spend']} />
                <Area type="monotone" dataKey="cost_usd" stroke={CHART.amber} fill="url(#costGrad)" strokeWidth={2} />
              </AreaChart>
            </ResponsiveContainer>
          </ChartState>
        </ChartCard>

        <ChartCard title="Job match sources">
          <ChartState isLoading={loading} error={error} empty={!sourceData.length}>
            <ResponsiveContainer width="100%" height={260}>
              <BarChart data={sourceData}>
                <CartesianGrid strokeDasharray="3 3" stroke={CHART.grid} />
                <XAxis dataKey="source" tick={CHART.tick} />
                <YAxis tick={CHART.tick} allowDecimals={false} />
                <Tooltip contentStyle={CHART.tooltip} />
                <Bar dataKey="count" fill={CHART.green} radius={[4, 4, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </ChartState>
        </ChartCard>
      </div>

      <div className="grid grid-cols-1 xl:grid-cols-2 gap-6">
        <ChartCard title="Pipeline health">
          <ChartState isLoading={loading} error={error} empty={!analytics?.pipeline_health?.length}>
            <ResponsiveContainer width="100%" height={260}>
              <LineChart data={analytics?.pipeline_health}>
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

        {/* Provider pricing (read-only) */}
        <div className="bg-card border border-line rounded-card p-5">
          <h3 className="text-sm font-semibold text-ink mb-4">LLM provider pricing</h3>
          {providers.length === 0 ? (
            <div className="h-[260px] flex items-center justify-center text-ink-faint text-sm">No provider pricing configured</div>
          ) : (
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-line text-ink-faint text-xs uppercase tracking-wide">
                  <th className="py-2 text-left">Provider</th>
                  <th className="py-2 text-right">In / 1M tok</th>
                  <th className="py-2 text-right">Out / 1M tok</th>
                  <th className="py-2 text-right">Status</th>
                </tr>
              </thead>
              <tbody>
                {providers.map((p, i) => (
                  <tr key={`${p.provider}-${i}`} className="border-b border-line/60">
                    <td className="py-2 text-ink">{p.provider}</td>
                    <td className="py-2 text-right font-mono text-ink-mute">${p.input_cost_per_1m_tokens}</td>
                    <td className="py-2 text-right font-mono text-ink-mute">${p.output_cost_per_1m_tokens}</td>
                    <td className="py-2 text-right">
                      <span className={`text-xs px-2 py-0.5 rounded-full ${p.active ? 'bg-accent-soft text-primary' : 'bg-surface-2 text-ink-faint'}`}>
                        {p.active ? 'active' : 'inactive'}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      </div>
    </div>
  );
}

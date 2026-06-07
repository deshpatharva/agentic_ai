import { useEffect, useState } from 'react';
import { Users, Activity, FileText, Zap, AlertTriangle } from 'lucide-react';
import client from '../../api/client';

function StatCard({ label, value, icon: Icon, color }) {
  return (
    <div className="bg-gray-900 border border-gray-800 rounded-xl p-5">
      <div className="flex items-center justify-between">
        <div>
          <p className="text-xs text-gray-500 uppercase tracking-wide">{label}</p>
          <p className="text-2xl font-bold text-white mt-1">
            {value ?? <span className="text-gray-600">—</span>}
          </p>
        </div>
        <div className={`w-10 h-10 rounded-lg flex items-center justify-center ${color}`}>
          <Icon className="w-5 h-5 text-white" />
        </div>
      </div>
    </div>
  );
}

export default function AdminDashboard() {
  const [stats, setStats] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    client.get('/admin/stats')
      .then(r => setStats(r.data))
      .finally(() => setLoading(false));
  }, []);

  const cards = [
    { label: 'Total Users',         key: 'total_users',         icon: Users,         color: 'bg-blue-600' },
    { label: 'Active Users',         key: 'active_users',        icon: Activity,      color: 'bg-green-600' },
    { label: 'Pipeline Runs Today',  key: 'pipeline_runs_today', icon: Zap,           color: 'bg-purple-600' },
    { label: 'Total Resumes Stored', key: 'total_resumes',       icon: FileText,      color: 'bg-orange-600' },
    {
      label: 'Stuck Jobs',
      key: 'stuck_jobs',
      icon: AlertTriangle,
      color: stats?.stuck_jobs > 0 ? 'bg-amber-500' : 'bg-gray-600',
    },
  ];

  return (
    <div className="p-8">
      <h1 className="text-xl font-bold text-white mb-6">Dashboard</h1>
      {loading ? (
        <div className="grid grid-cols-2 gap-4">
          {[...Array(5)].map((_, i) => (
            <div key={i} className="h-24 bg-gray-900 border border-gray-800 rounded-xl animate-pulse" />
          ))}
        </div>
      ) : (
        <div className="grid grid-cols-2 gap-4">
          {cards.map(c => (
            <StatCard key={c.key} label={c.label} value={stats?.[c.key]} icon={c.icon} color={c.color} />
          ))}
        </div>
      )}
    </div>
  );
}

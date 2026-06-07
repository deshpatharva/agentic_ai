import React, { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import UserGrowthChart from '../components/UserGrowthChart';
import PlanDistributionChart from '../components/PlanDistributionChart';
import CostTrendChart from '../components/CostTrendChart';
import SourceBreakdownChart from '../components/SourceBreakdownChart';
import PipelineHealthChart from '../components/PipelineHealthChart';

export default function AdminAnalytics() {
  const navigate = useNavigate();
  const [analytics, setAnalytics] = useState(null);
  const [days, setDays] = useState(30);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    const fetchAnalytics = async () => {
      setLoading(true);
      setError(null);
      try {
        const res = await fetch(`/api/admin/analytics?days=${days}`);
        if (!res.ok) {
          if (res.status === 403) {
            navigate('/dashboard');
            return;
          }
          throw new Error('Failed to fetch analytics');
        }
        const data = await res.json();
        setAnalytics(data);
      } catch (err) {
        setError(err.message);
      } finally {
        setLoading(false);
      }
    };

    fetchAnalytics();
  }, [days, navigate]);

  if (loading) return <div className="p-8 text-center">Loading analytics...</div>;
  if (error) return <div className="p-8 text-red-600">Error: {error}</div>;
  if (!analytics) return <div className="p-8 text-gray-600">No analytics available</div>;

  return (
    <div className="max-w-7xl mx-auto p-8">
      <div className="flex justify-between items-center mb-8">
        <h1 className="text-3xl font-bold">Admin Analytics</h1>
        <select
          value={days}
          onChange={(e) => setDays(parseInt(e.target.value))}
          className="px-4 py-2 border rounded-lg"
        >
          <option value={7}>Last 7 days</option>
          <option value={30}>Last 30 days</option>
          <option value={90}>Last 90 days</option>
        </select>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 mb-6">
        <UserGrowthChart data={analytics.user_growth} />
        <PlanDistributionChart data={analytics.plan_distribution} />
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 mb-6">
        <CostTrendChart data={analytics.daily_costs} />
        <SourceBreakdownChart data={analytics.source_counts} />
      </div>

      <div className="mb-6">
        <PipelineHealthChart data={analytics.pipeline_health} />
      </div>
    </div>
  );
}

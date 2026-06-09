import React, { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import client from '../api/client';
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
    setLoading(true);
    setError(null);
    client.get(`/admin/analytics?days=${days}`)
      .then(r => setAnalytics(r.data))
      .catch(err => {
        if (err.response?.status === 403) { navigate('/dashboard'); return; }
        setError(err.response?.data?.detail || 'Failed to fetch analytics');
      })
      .finally(() => setLoading(false));
  }, [days, navigate]);

  return (
    <div className="p-8">
      <div className="flex justify-between items-center mb-8">
        <h1 className="text-xl font-bold text-white">Analytics</h1>
        <select
          value={days}
          onChange={(e) => setDays(parseInt(e.target.value))}
          className="px-4 py-2 bg-gray-900 border border-gray-700 text-white rounded-lg text-sm focus:outline-none focus:border-gray-500"
        >
          <option value={7}>Last 7 days</option>
          <option value={30}>Last 30 days</option>
          <option value={90}>Last 90 days</option>
        </select>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 mb-6">
        <UserGrowthChart data={analytics?.user_growth} isLoading={loading} error={error} />
        <PlanDistributionChart data={analytics?.plan_distribution} isLoading={loading} error={error} />
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 mb-6">
        <CostTrendChart data={analytics?.daily_costs} isLoading={loading} error={error} />
        <SourceBreakdownChart data={analytics?.source_counts} isLoading={loading} error={error} />
      </div>

      <div className="mb-6">
        <PipelineHealthChart data={analytics?.pipeline_health} isLoading={loading} error={error} />
      </div>
    </div>
  );
}

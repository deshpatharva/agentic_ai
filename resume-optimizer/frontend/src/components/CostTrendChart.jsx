import React from 'react';
import {
  AreaChart,
  Area,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
} from 'recharts';

export default function CostTrendChart({ data, isLoading, error }) {
  if (isLoading) return <div className="p-6 text-center">Loading chart...</div>;
  if (error) return <div className="p-6 text-red-600">Error: {error}</div>;
  if (!data || data.length === 0) return <div className="p-6 text-gray-600">No cost data available</div>;

  const chartData = data.map(item => ({
    ...item,
    cost_dollars: (item.cost_cents / 100).toFixed(2),
  }));

  return (
    <div className="p-6 bg-white rounded-lg shadow">
      <h3 className="text-lg font-semibold mb-4">Cost Trend</h3>
      <ResponsiveContainer width="100%" height={300}>
        <AreaChart data={chartData}>
          <CartesianGrid strokeDasharray="3 3" />
          <XAxis dataKey="date" />
          <YAxis />
          <Tooltip formatter={(value) => `$${value}`} />
          <Area
            type="monotone"
            dataKey="cost_cents"
            stroke="#ef4444"
            fill="#fee2e2"
            formatter={(value) => `$${(value / 100).toFixed(2)}`}
          />
        </AreaChart>
      </ResponsiveContainer>
    </div>
  );
}

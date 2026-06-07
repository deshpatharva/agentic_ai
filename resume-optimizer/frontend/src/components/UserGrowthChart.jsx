import React from 'react';
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
  ResponsiveContainer,
} from 'recharts';

export default function UserGrowthChart({ data, isLoading, error }) {
  if (isLoading) return <div className="p-6 text-center">Loading...</div>;
  if (error) return <div className="p-6 text-red-600">Error: {error}</div>;
  if (!data || data.length === 0) return <div className="p-6 text-gray-600">No data</div>;

  return (
    <div className="p-6 bg-white rounded-lg shadow">
      <h3 className="text-lg font-semibold mb-4">User Growth</h3>
      <ResponsiveContainer width="100%" height={300}>
        <LineChart data={data}>
          <CartesianGrid strokeDasharray="3 3" />
          <XAxis dataKey="date" />
          <YAxis />
          <Tooltip />
          <Legend />
          <Line type="monotone" dataKey="cumulative_users" stroke="#3b82f6" name="Cumulative Users" />
          <Line type="monotone" dataKey="daily_signups" stroke="#10b981" name="Daily Signups" />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}

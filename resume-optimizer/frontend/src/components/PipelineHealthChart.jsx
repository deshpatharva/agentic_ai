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

export default function PipelineHealthChart({ data, isLoading, error }) {
  if (isLoading) return <div className="p-6 text-center">Loading...</div>;
  if (error) return <div className="p-6 text-red-600">Error: {error}</div>;
  if (!data || data.length === 0) return <div className="p-6 text-gray-600">No data</div>;

  return (
    <div className="p-6 bg-white rounded-lg shadow">
      <h3 className="text-lg font-semibold mb-4">Pipeline Health</h3>
      <ResponsiveContainer width="100%" height={300}>
        <LineChart data={data}>
          <CartesianGrid strokeDasharray="3 3" />
          <XAxis dataKey="date" />
          <YAxis />
          <Tooltip />
          <Legend />
          <Line type="monotone" dataKey="successful" stroke="#10b981" name="Successful Runs" />
          <Line type="monotone" dataKey="failed" stroke="#ef4444" name="Failed Runs" />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}

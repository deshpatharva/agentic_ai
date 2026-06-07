import React, { useState } from 'react';
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

export default function UsageTrendsChart({ data, isLoading, error }) {
  const [metric, setMetric] = useState('pipeline_runs');

  if (isLoading) return <div className="p-6 text-center">Loading chart...</div>;
  if (error) return <div className="p-6 text-red-600">Error: {error}</div>;
  if (!data || data.length === 0) return <div className="p-6 text-gray-600">No data available</div>;

  return (
    <div className="p-6 bg-white rounded-lg shadow">
      <div className="flex justify-between items-center mb-4">
        <h3 className="text-lg font-semibold">Usage Trends</h3>
        <div className="flex gap-2">
          <button
            onClick={() => setMetric('pipeline_runs')}
            className={`px-3 py-1 text-sm rounded ${metric === 'pipeline_runs' ? 'bg-blue-500 text-white' : 'bg-gray-200'}`}
          >
            Runs
          </button>
          <button
            onClick={() => setMetric('uploads')}
            className={`px-3 py-1 text-sm rounded ${metric === 'uploads' ? 'bg-blue-500 text-white' : 'bg-gray-200'}`}
          >
            Uploads
          </button>
          <button
            onClick={() => setMetric('tokens_used')}
            className={`px-3 py-1 text-sm rounded ${metric === 'tokens_used' ? 'bg-blue-500 text-white' : 'bg-gray-200'}`}
          >
            Tokens
          </button>
        </div>
      </div>
      <ResponsiveContainer width="100%" height={300}>
        <LineChart data={data}>
          <CartesianGrid strokeDasharray="3 3" />
          <XAxis dataKey="date" />
          <YAxis />
          <Tooltip />
          <Legend />
          {metric === 'pipeline_runs' && <Line type="monotone" dataKey="pipeline_runs" stroke="#3b82f6" />}
          {metric === 'uploads' && <Line type="monotone" dataKey="uploads" stroke="#10b981" />}
          {metric === 'tokens_used' && <Line type="monotone" dataKey="tokens_used" stroke="#f59e0b" />}
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}

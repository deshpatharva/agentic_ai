import React from 'react';
import {
  ComposedChart,
  Bar,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
  ResponsiveContainer,
} from 'recharts';

export default function MatchAnalytics({ data, isLoading, error }) {
  if (isLoading) return <div className="p-6 text-center">Loading chart...</div>;
  if (error) return <div className="p-6 text-red-600">Error: {error}</div>;
  if (!data || data.length === 0) return <div className="p-6 text-gray-600">No match data available</div>;

  return (
    <div className="p-6 bg-white rounded-lg shadow">
      <h3 className="text-lg font-semibold mb-4">Job Match Quality</h3>
      <ResponsiveContainer width="100%" height={300}>
        <ComposedChart data={data}>
          <CartesianGrid strokeDasharray="3 3" />
          <XAxis dataKey="date" />
          <YAxis yAxisId="left" label={{ value: 'Match Count', angle: -90, position: 'insideLeft' }} />
          <YAxis
            yAxisId="right"
            orientation="right"
            domain={[0, 1]}
            label={{ value: 'Avg Similarity', angle: 90, position: 'insideRight' }}
          />
          <Tooltip />
          <Legend />
          <Bar yAxisId="left" dataKey="match_count" fill="#3b82f6" name="Match Count" />
          <Line
            yAxisId="right"
            type="monotone"
            dataKey="avg_similarity_score"
            stroke="#10b981"
            name="Avg Similarity"
          />
        </ComposedChart>
      </ResponsiveContainer>
    </div>
  );
}

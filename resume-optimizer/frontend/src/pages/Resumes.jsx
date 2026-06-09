import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { Download, FileText, ChevronLeft, ChevronRight } from 'lucide-react';
import Sidebar from '../components/layout/Sidebar';
import Card from '../components/ui/Card';
import client from '../api/client';

function scoreColor(s) {
  if (s >= 85) return 'text-green-600 bg-green-50';
  if (s >= 70) return 'text-amber-600 bg-amber-50';
  return 'text-red-600 bg-red-50';
}

export default function Resumes() {
  const [resumes, setResumes] = useState([]);
  const [total, setTotal]     = useState(0);
  const [page, setPage]       = useState(1);
  const [loading, setLoading] = useState(true);
  const perPage = 10;

  useEffect(() => {
    setLoading(true);
    client.get('/dashboard/resumes', { params: { page, per_page: perPage } })
      .then(r => { setResumes(r.data.results); setTotal(r.data.total); })
      .finally(() => setLoading(false));
  }, [page]);

  const totalPages = Math.ceil(total / perPage);

  return (
    <div className="flex h-screen bg-surface overflow-hidden page-fade">
      <Sidebar />
      <main className="flex-1 overflow-y-auto">
        <div className="max-w-4xl mx-auto px-8 py-8">
          <div className="flex items-center justify-between mb-6">
            <div>
              <h1 className="text-2xl font-bold text-gray-900">My Resumes</h1>
              <p className="text-gray-500 text-sm mt-1">{total} resume{total !== 1 ? 's' : ''} optimized</p>
            </div>
            <Link
              to="/app"
              className="flex items-center gap-2 px-4 py-2 bg-primary text-white rounded-xl text-sm font-medium hover:bg-primary-dark transition-colors"
            >
              <FileText className="w-4 h-4" /> Optimize New Resume
            </Link>
          </div>

          <Card>
            {loading ? (
              <div className="py-16 text-center text-gray-400">Loading…</div>
            ) : resumes.length === 0 ? (
              <div className="py-16 text-center">
                <FileText className="w-10 h-10 text-gray-200 mx-auto mb-3" />
                <p className="text-gray-400 text-sm">No resumes yet.</p>
                <Link to="/app" className="text-primary text-sm hover:underline mt-1 inline-block">
                  Optimize your first resume →
                </Link>
              </div>
            ) : (
              <table className="w-full text-sm">
                <thead>
                  <tr className="text-left text-xs text-gray-400 border-b border-gray-100">
                    <th className="pb-3 font-medium">File</th>
                    <th className="pb-3 font-medium">Score</th>
                    <th className="pb-3 font-medium">Iterations</th>
                    <th className="pb-3 font-medium">Version</th>
                    <th className="pb-3 font-medium">Date</th>
                    <th className="pb-3 font-medium"></th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-50">
                  {resumes.map(r => (
                    <tr key={r.id} className="hover:bg-gray-50 transition-colors">
                      <td className="py-3 font-medium text-gray-800 truncate max-w-[200px]">{r.filename}</td>
                      <td className="py-3">
                        <span className={`inline-block px-2 py-0.5 rounded-full text-xs font-medium ${scoreColor(r.final_score || 0)}`}>
                          {r.final_score ? Math.round(r.final_score) : '—'}
                        </span>
                      </td>
                      <td className="py-3 text-gray-500">{r.iterations}</td>
                      <td className="py-3 text-gray-400">v{r.version}</td>
                      <td className="py-3 text-gray-400 text-xs">
                        {new Date(r.created_at).toLocaleDateString()}
                      </td>
                      <td className="py-3">
                        <a
                          href={r.download_url}
                          download
                          className="flex items-center gap-1 text-primary hover:text-primary-dark text-xs font-medium"
                        >
                          <Download className="w-3 h-3" /> Download
                        </a>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </Card>

          {totalPages > 1 && (
            <div className="flex items-center justify-center gap-3 mt-5">
              <button
                disabled={page === 1}
                onClick={() => setPage(p => p - 1)}
                className="p-2 text-gray-400 hover:text-gray-700 disabled:opacity-30 transition-colors"
              >
                <ChevronLeft className="w-4 h-4" />
              </button>
              <span className="text-sm text-gray-500">Page {page} of {totalPages}</span>
              <button
                disabled={page === totalPages}
                onClick={() => setPage(p => p + 1)}
                className="p-2 text-gray-400 hover:text-gray-700 disabled:opacity-30 transition-colors"
              >
                <ChevronRight className="w-4 h-4" />
              </button>
            </div>
          )}
        </div>
      </main>
    </div>
  );
}

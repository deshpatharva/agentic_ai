import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { Download, FileText, ChevronLeft, ChevronRight } from 'lucide-react';
import AppShell from '../components/layout/AppShell';
import Card from '../components/ui/Card';
import client, { buildDownloadUrl } from '../api/client';

function scoreColor(s) {
  if (s >= 85) return 'text-primary bg-accent-soft';
  if (s >= 70) return 'text-hilite bg-hilite-soft';
  return 'text-err bg-err-soft';
}

export default function Resumes() {
  const [resumes, setResumes] = useState([]);
  const [total, setTotal]     = useState(0);
  const [page, setPage]       = useState(1);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState(null);
  const perPage = 10;

  useEffect(() => {
    setLoading(true);
    setLoadError(null);
    client.get('/dashboard/resumes', { params: { page, per_page: perPage } })
      .then(r => { setResumes(r.data.results); setTotal(r.data.total); })
      .catch(err => setLoadError(err.response?.data?.detail || 'Could not load your resumes.'))
      .finally(() => setLoading(false));
  }, [page]);

  const totalPages = Math.ceil(total / perPage);

  return (
    <AppShell>
      <div className="page-fade">
        <div className="max-w-4xl mx-auto px-4 sm:px-8 py-8">
          <div className="flex flex-wrap items-center justify-between gap-3 mb-6">
            <div>
              <h1 className="font-display text-2xl font-semibold text-ink">My Resumes</h1>
              <p className="text-ink-mute text-sm mt-1">{total} resume{total !== 1 ? 's' : ''} optimized</p>
            </div>
            <Link
              to="/optimize"
              className="flex items-center gap-2 px-4 py-2 bg-primary text-white dark:text-ink rounded-lg text-sm font-medium hover:bg-primary-dark transition-colors"
            >
              <FileText className="w-4 h-4" /> Optimize New Resume
            </Link>
          </div>

          <Card>
            {loading ? (
              <div className="py-16 text-center text-ink-faint">Loading…</div>
            ) : loadError ? (
              <div className="py-16 text-center text-sm text-err">{String(loadError)}</div>
            ) : resumes.length === 0 ? (
              <div className="py-16 text-center">
                <FileText className="w-10 h-10 text-ink-faint/40 mx-auto mb-3" />
                <p className="text-ink-faint text-sm">No resumes yet.</p>
                <Link to="/optimize" className="text-primary text-sm hover:underline mt-1 inline-block">
                  Optimize your first resume →
                </Link>
              </div>
            ) : (
              <div className="overflow-x-auto">
              <table className="w-full text-sm min-w-[560px]">
                <thead>
                  <tr className="text-left text-xs text-ink-faint border-b border-line">
                    <th className="pb-3 font-medium">File</th>
                    <th className="pb-3 font-medium">Score</th>
                    <th className="pb-3 font-medium">Iterations</th>
                    <th className="pb-3 font-medium">Version</th>
                    <th className="pb-3 font-medium">Date</th>
                    <th className="pb-3 font-medium"></th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-line/50">
                  {resumes.map(r => (
                    <tr key={r.id} className="hover:bg-surface-2 transition-colors">
                      <td className="py-3 font-medium text-ink truncate max-w-[200px]">{r.filename}</td>
                      <td className="py-3">
                        <span className={`inline-block px-2 py-0.5 rounded-full text-xs font-medium font-mono ${scoreColor(r.final_score || 0)}`}>
                          {r.final_score ? Math.round(r.final_score) : '—'}
                        </span>
                      </td>
                      <td className="py-3 text-ink-mute">{r.iterations}</td>
                      <td className="py-3 text-ink-faint">v{r.version}</td>
                      <td className="py-3 text-ink-faint text-xs">
                        {new Date(r.created_at).toLocaleDateString()}
                      </td>
                      <td className="py-3">
                        <a
                          href={buildDownloadUrl(r.download_url)}
                          className="flex items-center gap-1 text-primary hover:text-primary-dark text-xs font-medium"
                        >
                          <Download className="w-3 h-3" /> Download
                        </a>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
              </div>
            )}
          </Card>

          {totalPages > 1 && (
            <div className="flex items-center justify-center gap-3 mt-5">
              <button
                disabled={page === 1}
                onClick={() => setPage(p => p - 1)}
                aria-label="Previous page"
                className="p-2 text-ink-faint hover:text-ink disabled:opacity-30 transition-colors"
              >
                <ChevronLeft className="w-4 h-4" />
              </button>
              <span className="text-sm text-ink-mute">Page {page} of {totalPages}</span>
              <button
                disabled={page === totalPages}
                onClick={() => setPage(p => p + 1)}
                aria-label="Next page"
                className="p-2 text-ink-faint hover:text-ink disabled:opacity-30 transition-colors"
              >
                <ChevronRight className="w-4 h-4" />
              </button>
            </div>
          )}
        </div>
      </div>
    </AppShell>
  );
}

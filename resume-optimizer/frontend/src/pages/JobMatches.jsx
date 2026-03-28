import { useEffect, useState } from 'react';
import { ExternalLink, Lock, Zap } from 'lucide-react';
import { Link } from 'react-router-dom';
import Sidebar from '../components/layout/Sidebar';
import Card from '../components/ui/Card';
import Badge from '../components/ui/Badge';
import client from '../api/client';
import useAuthStore from '../store/authStore';

const sourceBadge = { adzuna: 'green', remoteok: 'blue', the_muse: 'teal', apify: 'pro' };

export default function JobMatches() {
  const { user } = useAuthStore();
  const [matches, setMatches] = useState([]);
  const [loading, setLoading] = useState(true);
  const isPro = user?.plan === 'pro' || user?.plan === 'enterprise';

  useEffect(() => {
    if (!isPro) { setLoading(false); return; }
    client.get('/dashboard/job-matches').then(r => setMatches(r.data.results || [])).finally(() => setLoading(false));
  }, [isPro]);

  if (!isPro) return (
    <div className="flex h-screen bg-surface overflow-hidden">
      <Sidebar />
      <main className="flex-1 flex items-center justify-center">
        <div className="text-center max-w-sm">
          <Lock className="w-12 h-12 text-gray-300 mx-auto mb-4" />
          <h2 className="text-xl font-bold text-gray-800 mb-2">Job Matching is a Pro feature</h2>
          <p className="text-gray-500 text-sm mb-6">Upgrade to get nightly job matches from Adzuna, RemoteOK, and The Muse.</p>
          <Link to="/dashboard/settings" className="bg-primary text-white px-6 py-2.5 rounded-xl font-medium inline-flex items-center gap-2 hover:bg-primary-dark transition-colors">
            <Zap className="w-4 h-4" /> Upgrade to Pro
          </Link>
        </div>
      </main>
    </div>
  );

  return (
    <div className="flex h-screen bg-surface overflow-hidden">
      <Sidebar />
      <main className="flex-1 overflow-y-auto">
        <div className="max-w-4xl mx-auto px-8 py-8">
          <h1 className="text-2xl font-bold text-gray-900 mb-6">Job Matches</h1>
          {loading ? <p className="text-gray-400">Loading…</p> : matches.length === 0 ? (
            <Card><p className="text-sm text-gray-400 text-center py-8">No job matches yet. Run the job scraper to find matched roles.</p></Card>
          ) : (
            <div className="space-y-4">
              {matches.map((m, i) => (
                <div key={i} className="bg-white rounded-2xl border border-gray-100 p-5 shadow-sm flex items-start gap-4">
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2 mb-1">
                      <h3 className="font-semibold text-gray-900 truncate">{m.job_title}</h3>
                      {!m.is_read && <span className="w-2 h-2 rounded-full bg-primary shrink-0" />}
                    </div>
                    <p className="text-sm text-gray-500 mb-2">{m.company || 'Company not listed'}</p>
                    <div className="flex items-center gap-2">
                      <Badge variant={sourceBadge[m.source] || 'free'}>{m.source}</Badge>
                      {m.similarity_score != null && (
                        <span className="text-xs text-gray-400">{Math.round(m.similarity_score * 100)}% match</span>
                      )}
                      <span className="text-xs text-gray-300">{new Date(m.scraped_at).toLocaleDateString()}</span>
                    </div>
                  </div>
                  {m.url && (
                    <a href={m.url} target="_blank" rel="noopener noreferrer"
                      className="shrink-0 bg-primary/10 hover:bg-primary/20 text-primary px-3 py-1.5 rounded-lg text-sm font-medium flex items-center gap-1 transition-colors">
                      Apply <ExternalLink className="w-3 h-3" />
                    </a>
                  )}
                </div>
              ))}
            </div>
          )}
        </div>
      </main>
    </div>
  );
}

import { useEffect, useState } from 'react';
import { ExternalLink, Lock, Zap } from 'lucide-react';
import { Link } from 'react-router-dom';
import AppShell from '../components/layout/AppShell';
import Card from '../components/ui/Card';
import Badge from '../components/ui/Badge';
import client from '../api/client';
import useAuthStore from '../store/authStore';

const sourceBadge = { adzuna: 'green', remoteok: 'blue', the_muse: 'teal', apify: 'pro' };

export default function JobMatches() {
  const { user } = useAuthStore();
  const [matches, setMatches] = useState([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState(null);
  const isPro = user?.plan === 'pro' || user?.plan === 'enterprise';

  useEffect(() => {
    if (!isPro) { setLoading(false); return; }
    client.get('/dashboard/job-matches')
      .then(r => setMatches(r.data.results || []))
      .catch(err => setLoadError(err.response?.data?.detail || 'Could not load job matches.'))
      .finally(() => setLoading(false));
  }, [isPro]);

  if (!isPro) return (
    <AppShell>
      <div className="h-full flex items-center justify-center page-fade px-4">
        <div className="text-center max-w-sm">
          <div className="bg-surface-2 p-4 rounded-card inline-flex items-center justify-center mb-4">
            <Lock className="w-10 h-10 text-ink-faint" />
          </div>
          <h2 className="font-display text-xl font-semibold text-ink mb-2">Job Matching is a Pro feature</h2>
          <p className="text-ink-mute text-sm mb-6">Upgrade to get nightly job matches from Adzuna, RemoteOK, and The Muse.</p>
          <Link to="/dashboard/settings" className="bg-primary text-white dark:text-ink px-6 py-2.5 rounded-lg font-medium inline-flex items-center gap-2 hover:bg-primary-dark transition-colors">
            <Zap className="w-4 h-4" /> Upgrade to Pro
          </Link>
        </div>
      </div>
    </AppShell>
  );

  return (
    <AppShell>
      <div className="page-fade">
        <div className="max-w-4xl mx-auto px-4 sm:px-8 py-8">
          <h1 className="font-display text-2xl font-semibold text-ink mb-6">Job Matches</h1>
          {loading ? <p className="text-ink-faint">Loading…</p> : loadError ? (
            <Card><p className="text-sm text-err text-center py-8">{String(loadError)}</p></Card>
          ) : matches.length === 0 ? (
            <Card><p className="text-sm text-ink-faint text-center py-8">No job matches yet. Run the job scraper to find matched roles.</p></Card>
          ) : (
            <div className="space-y-4">
              {matches.map((m) => (
                <div key={m.id || m.url || `${m.job_title}-${m.scraped_at}`} className="bg-card rounded-card border border-line p-5 shadow-card flex items-start gap-4">
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2 mb-1">
                      <h3 className="font-semibold text-ink truncate">{m.job_title}</h3>
                      {!m.is_read && <span className="w-2 h-2 rounded-full bg-primary shrink-0" />}
                    </div>
                    <p className="text-sm text-ink-mute mb-1">{m.company || 'Company not listed'}</p>
                    {m.similarity_score != null && (
                      <div className="flex items-center gap-2 mt-1 mb-2">
                        <div className="flex-1 h-1.5 bg-surface-2 rounded-full overflow-hidden">
                          <div
                            className="h-1.5 rounded-full bg-primary"
                            style={{ width: `${Math.round(m.similarity_score * 100)}%` }}
                          />
                        </div>
                        <span className="text-xs font-bold font-mono text-primary">
                          {Math.round(m.similarity_score * 100)}%
                        </span>
                      </div>
                    )}
                    <div className="flex items-center gap-2">
                      <Badge variant={sourceBadge[m.source] || 'free'}>{m.source}</Badge>
                      <span className="text-xs text-ink-faint">{new Date(m.scraped_at).toLocaleDateString()}</span>
                    </div>
                  </div>
                  {m.url && (
                    <a href={m.url} target="_blank" rel="noopener noreferrer"
                      className="shrink-0 bg-accent-soft hover:bg-primary/20 text-primary px-3 py-1.5 rounded-lg text-sm font-medium flex items-center gap-1 transition-colors">
                      Apply <ExternalLink className="w-3 h-3" />
                    </a>
                  )}
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </AppShell>
  );
}

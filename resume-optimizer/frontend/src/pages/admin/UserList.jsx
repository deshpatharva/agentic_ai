import { useEffect, useState, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import { Search, ChevronRight } from 'lucide-react';
import client from '../../api/client';

const PLAN_BADGE = {
  free:       'bg-surface-2 text-ink-mute',
  pro:        'bg-accent-soft text-primary',
  enterprise: 'bg-hilite-soft text-hilite',
};

export default function UserList() {
  const navigate = useNavigate();
  const [users, setUsers]       = useState([]);
  const [total, setTotal]       = useState(0);
  const [page, setPage]         = useState(1);
  const [search, setSearch]     = useState('');
  const [rawInput, setRawInput] = useState('');
  const [loading, setLoading]   = useState(true);
  const perPage = 20;

  // Debounce raw input → search
  useEffect(() => {
    const t = setTimeout(() => { setSearch(rawInput); setPage(1); }, 300);
    return () => clearTimeout(t);
  }, [rawInput]);

  const fetchUsers = useCallback(() => {
    setLoading(true);
    const params = new URLSearchParams({ page, per_page: perPage });
    if (search) params.set('search', search);
    client.get(`/admin/users?${params}`)
      .then(r => { setUsers(r.data.results); setTotal(r.data.total); })
      .finally(() => setLoading(false));
  }, [page, search]);

  useEffect(() => { fetchUsers(); }, [fetchUsers]);

  const totalPages = Math.ceil(total / perPage);

  return (
    <div className="p-4 sm:p-8">
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-xl font-bold text-ink">
          Users <span className="text-ink-faint text-base font-normal">({total})</span>
        </h1>
        <div className="relative">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-ink-faint" />
          <input
            type="text"
            placeholder="Search by email…"
            value={rawInput}
            onChange={e => setRawInput(e.target.value)}
            className="pl-9 pr-4 py-2 bg-card border border-line rounded-lg text-sm text-ink placeholder:text-ink-faint focus:outline-none focus:border-primary w-56"
          />
        </div>
      </div>

      <div className="bg-card border border-line rounded-card overflow-hidden">
        <div className="overflow-x-auto">
        <table className="w-full text-sm min-w-[640px]">
          <thead>
            <tr className="border-b border-line text-ink-faint text-xs uppercase tracking-wide">
              <th className="px-4 py-3 text-left">Email</th>
              <th className="px-4 py-3 text-left">Plan</th>
              <th className="px-4 py-3 text-left">Status</th>
              <th className="px-4 py-3 text-left">Resumes</th>
              <th className="px-4 py-3 text-left">Joined</th>
              <th className="px-4 py-3 w-8" />
            </tr>
          </thead>
          <tbody>
            {loading ? (
              <tr>
                <td colSpan={6} className="px-4 py-10 text-center text-ink-faint">Loading…</td>
              </tr>
            ) : users.length === 0 ? (
              <tr>
                <td colSpan={6} className="px-4 py-10 text-center text-ink-faint">No users found.</td>
              </tr>
            ) : users.map(u => (
              <tr
                key={u.id}
                onClick={() => navigate(`/admin/users/${u.id}`)}
                className="border-b border-line/60 hover:bg-surface-2/60 cursor-pointer transition-colors"
              >
                <td className="px-4 py-3 text-ink">
                  {u.email}
                  {u.is_admin && (
                    <span className="ml-2 text-xs bg-err-soft text-err px-1.5 py-0.5 rounded">admin</span>
                  )}
                </td>
                <td className="px-4 py-3">
                  <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${PLAN_BADGE[u.plan] || PLAN_BADGE.free}`}>
                    {u.plan}
                  </span>
                </td>
                <td className="px-4 py-3">
                  <span className={`text-xs px-2 py-0.5 rounded-full ${u.is_active ? 'bg-accent-soft text-primary' : 'bg-err-soft text-err'}`}>
                    {u.is_active ? 'Active' : 'Suspended'}
                  </span>
                </td>
                <td className="px-4 py-3 text-ink-mute">{u.resume_count}</td>
                <td className="px-4 py-3 text-ink-mute">{new Date(u.created_at).toLocaleDateString()}</td>
                <td className="px-4 py-3 text-ink-faint"><ChevronRight className="w-4 h-4" /></td>
              </tr>
            ))}
          </tbody>
        </table>
        </div>
      </div>

      {totalPages > 1 && (
        <div className="flex items-center justify-center gap-3 mt-5">
          <button
            disabled={page === 1}
            onClick={() => setPage(p => p - 1)}
            className="px-3 py-1.5 text-sm text-ink-mute bg-card border border-line rounded-lg disabled:opacity-40 hover:bg-surface-2 transition-colors"
          >
            Prev
          </button>
          <span className="text-sm text-ink-faint">Page {page} of {totalPages}</span>
          <button
            disabled={page === totalPages}
            onClick={() => setPage(p => p + 1)}
            className="px-3 py-1.5 text-sm text-ink-mute bg-card border border-line rounded-lg disabled:opacity-40 hover:bg-surface-2 transition-colors"
          >
            Next
          </button>
        </div>
      )}
    </div>
  );
}

import { useEffect, useState, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import { Search, ChevronRight } from 'lucide-react';
import client from '../../api/client';

const PLAN_BADGE = {
  free:       'bg-gray-700 text-gray-200',
  pro:        'bg-blue-900 text-blue-200',
  enterprise: 'bg-purple-900 text-purple-200',
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
    <div className="p-8">
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-xl font-bold text-white">
          Users <span className="text-gray-500 text-base font-normal">({total})</span>
        </h1>
        <div className="relative">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-500" />
          <input
            type="text"
            placeholder="Search by email…"
            value={rawInput}
            onChange={e => setRawInput(e.target.value)}
            className="pl-9 pr-4 py-2 bg-gray-900 border border-gray-700 rounded-lg text-sm text-white placeholder-gray-500 focus:outline-none focus:border-gray-500 w-56"
          />
        </div>
      </div>

      <div className="bg-gray-900 border border-gray-800 rounded-xl overflow-hidden">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-gray-800 text-gray-500 text-xs uppercase tracking-wide">
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
                <td colSpan={6} className="px-4 py-10 text-center text-gray-600">Loading…</td>
              </tr>
            ) : users.length === 0 ? (
              <tr>
                <td colSpan={6} className="px-4 py-10 text-center text-gray-600">No users found.</td>
              </tr>
            ) : users.map(u => (
              <tr
                key={u.id}
                onClick={() => navigate(`/admin/users/${u.id}`)}
                className="border-b border-gray-800 hover:bg-gray-800 cursor-pointer transition-colors"
              >
                <td className="px-4 py-3 text-white">
                  {u.email}
                  {u.is_admin && (
                    <span className="ml-2 text-xs bg-red-900 text-red-300 px-1.5 py-0.5 rounded">admin</span>
                  )}
                </td>
                <td className="px-4 py-3">
                  <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${PLAN_BADGE[u.plan] || PLAN_BADGE.free}`}>
                    {u.plan}
                  </span>
                </td>
                <td className="px-4 py-3">
                  <span className={`text-xs px-2 py-0.5 rounded-full ${u.is_active ? 'bg-green-900 text-green-300' : 'bg-red-900 text-red-300'}`}>
                    {u.is_active ? 'Active' : 'Suspended'}
                  </span>
                </td>
                <td className="px-4 py-3 text-gray-400">{u.resume_count}</td>
                <td className="px-4 py-3 text-gray-400">{new Date(u.created_at).toLocaleDateString()}</td>
                <td className="px-4 py-3 text-gray-600"><ChevronRight className="w-4 h-4" /></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {totalPages > 1 && (
        <div className="flex items-center justify-center gap-3 mt-5">
          <button
            disabled={page === 1}
            onClick={() => setPage(p => p - 1)}
            className="px-3 py-1.5 text-sm text-gray-400 bg-gray-900 border border-gray-700 rounded-lg disabled:opacity-40 hover:bg-gray-800 transition-colors"
          >
            Prev
          </button>
          <span className="text-sm text-gray-500">Page {page} of {totalPages}</span>
          <button
            disabled={page === totalPages}
            onClick={() => setPage(p => p + 1)}
            className="px-3 py-1.5 text-sm text-gray-400 bg-gray-900 border border-gray-700 rounded-lg disabled:opacity-40 hover:bg-gray-800 transition-colors"
          >
            Next
          </button>
        </div>
      )}
    </div>
  );
}

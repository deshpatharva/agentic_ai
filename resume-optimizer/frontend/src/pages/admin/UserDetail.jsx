import { useEffect, useState } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { ArrowLeft, Shield } from 'lucide-react';
import toast from 'react-hot-toast';
import client from '../../api/client';
import useAuthStore from '../../store/authStore';

const PLANS = ['free', 'pro', 'enterprise'];

export default function UserDetail() {
  const { id } = useParams();
  const navigate = useNavigate();
  const { user: me } = useAuthStore();
  const [user, setUser]     = useState(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving]   = useState(false);

  useEffect(() => {
    client.get(`/admin/users/${id}`)
      .then(r => setUser(r.data))
      .catch(() => navigate('/admin/users'))
      .finally(() => setLoading(false));
  }, [id, navigate]);

  const patch = async (body) => {
    setSaving(true);
    try {
      const r = await client.patch(`/admin/users/${id}`, body);
      setUser(r.data);
      toast.success('Saved');
    } catch (e) {
      toast.error(e.response?.data?.detail || 'Update failed');
    } finally {
      setSaving(false);
    }
  };

  if (loading) return <div className="p-8 text-ink-faint">Loading…</div>;
  if (!user) return null;

  const isSelf = me?.id === user.id;

  return (
    <div className="p-4 sm:p-8 max-w-xl">
      <button
        onClick={() => navigate('/admin/users')}
        className="flex items-center gap-1.5 text-sm text-ink-faint hover:text-ink mb-6 transition-colors"
      >
        <ArrowLeft className="w-4 h-4" /> Back to users
      </button>

      {/* Header */}
      <div className="flex items-start justify-between mb-6">
        <div>
          <h1 className="text-xl font-bold text-ink">{user.full_name || user.email}</h1>
          <p className="text-ink-mute text-sm mt-0.5">{user.email}</p>
          <p className="text-ink-faint text-xs mt-1">
            Joined {new Date(user.created_at).toLocaleDateString()}
          </p>
        </div>
        {user.is_admin && (
          <span className="flex items-center gap-1 text-xs bg-err-soft text-err px-2.5 py-1 rounded-full">
            <Shield className="w-3 h-3" /> Admin
          </span>
        )}
      </div>

      {/* Stats */}
      <div className="grid grid-cols-3 gap-3 mb-5">
        {[
          { label: 'Resumes',    value: user.total_resumes },
          { label: 'Runs today', value: user.runs_today },
          { label: 'Last active', value: user.last_active ? new Date(user.last_active).toLocaleDateString() : '—' },
        ].map(s => (
          <div key={s.label} className="bg-card border border-line rounded-card p-4">
            <p className="text-xs text-ink-faint">{s.label}</p>
            <p className="text-lg font-semibold font-mono text-ink mt-0.5">{s.value}</p>
          </div>
        ))}
      </div>

      {/* Plan */}
      <div className="bg-card border border-line rounded-card p-5 mb-3">
        <p className="text-xs text-ink-faint uppercase tracking-wide mb-3">Plan</p>
        <div className="flex gap-2">
          {PLANS.map(plan => (
            <button
              key={plan}
              disabled={saving || user.plan === plan}
              onClick={() => patch({ plan })}
              className={`px-4 py-2 rounded-lg text-sm font-medium capitalize transition-colors ${
                user.plan === plan
                  ? 'bg-primary text-white dark:text-ink'
                  : 'bg-surface-2 text-ink-mute hover:text-ink'
              } disabled:opacity-60`}
            >
              {plan}
            </button>
          ))}
        </div>
      </div>

      {/* Promote to admin */}
      {!user.is_admin && (
        <div className="bg-card border border-line rounded-card p-5 mb-3">
          <p className="text-xs text-ink-faint uppercase tracking-wide mb-3">Admin Access</p>
          <button
            disabled={saving}
            onClick={() => {
              if (confirm(`Promote ${user.email} to admin?`)) patch({ is_admin: true });
            }}
            className="px-4 py-2 bg-err-soft hover:bg-err/30 text-err rounded-lg text-sm font-medium transition-colors disabled:opacity-60"
          >
            Promote to admin
          </button>
        </div>
      )}

      {/* Suspend / reactivate */}
      {!user.is_admin && !isSelf && (
        <div className="bg-card border border-line rounded-card p-5">
          <p className="text-xs text-ink-faint uppercase tracking-wide mb-3">Account Status</p>
          <button
            disabled={saving}
            onClick={() => patch({ is_active: !user.is_active })}
            className={`px-4 py-2 rounded-lg text-sm font-medium transition-colors disabled:opacity-60 ${
              user.is_active
                ? 'bg-err-soft hover:bg-err/30 text-err'
                : 'bg-accent-soft hover:bg-primary/30 text-primary'
            }`}
          >
            {user.is_active ? 'Suspend account' : 'Reactivate account'}
          </button>
        </div>
      )}
    </div>
  );
}

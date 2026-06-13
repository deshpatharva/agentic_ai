import { useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { Eye, EyeOff } from 'lucide-react';
import toast from 'react-hot-toast';
import AuthLayout from '../components/layout/AuthLayout';
import Button from '../components/ui/Button';
import client from '../api/client';
import useAuthStore from '../store/authStore';

const inputCls = 'w-full bg-card text-ink border border-line rounded-lg px-4 py-2.5 text-sm placeholder:text-ink-faint focus:outline-none focus:ring-2 focus:ring-primary/30 focus:border-primary transition-all';

function StrengthBar({ password }) {
  const score = [/.{8,}/, /[A-Z]/, /[0-9]/, /[^A-Za-z0-9]/].filter(r => r.test(password)).length;
  const colors = ['bg-err', 'bg-hilite', 'bg-hilite', 'bg-primary'];
  const labels = ['Weak', 'Fair', 'Good', 'Strong'];
  if (!password) return null;
  return (
    <div className="mt-2">
      <div className="flex gap-1 mb-1">
        {[0,1,2,3].map(i => <div key={i} className={`h-1 flex-1 rounded-full ${i < score ? colors[score-1] : 'bg-surface-2'}`} />)}
      </div>
      <span className="text-xs text-ink-mute">{labels[score - 1] || 'Weak'}</span>
    </div>
  );
}

export default function Register() {
  const [form, setForm] = useState({ full_name: '', email: '', password: '', confirm: '' });
  const [show, setShow] = useState(false);
  const [loading, setLoading] = useState(false);
  const { login } = useAuthStore();
  const navigate = useNavigate();

  const submit = async (e) => {
    e.preventDefault();
    if (form.password !== form.confirm) { toast.error('Passwords do not match'); return; }
    if (form.password.length < 8) { toast.error('Password must be at least 8 characters'); return; }
    setLoading(true);
    try {
      const { data } = await client.post('/auth/register', { email: form.email, password: form.password, full_name: form.full_name });
      login(data.access_token, data.user);
      toast.success('Account created!');
      navigate('/optimize');
    } catch (err) {
      toast.error(err.response?.data?.detail || 'Registration failed');
    } finally {
      setLoading(false);
    }
  };

  return (
    <AuthLayout title="Create your account" subtitle="Start optimizing resumes for free">
      <form onSubmit={submit} className="space-y-5 page-fade">
        <div>
          <label className="block text-sm font-medium text-ink-mute mb-1.5">Full name</label>
          <input type="text" value={form.full_name} onChange={e => setForm(f => ({ ...f, full_name: e.target.value }))}
            className={inputCls}
            placeholder="Jane Smith" />
        </div>
        <div>
          <label className="block text-sm font-medium text-ink-mute mb-1.5">Email</label>
          <input type="email" required value={form.email} onChange={e => setForm(f => ({ ...f, email: e.target.value }))}
            className={inputCls}
            placeholder="you@example.com" />
        </div>
        <div>
          <label className="block text-sm font-medium text-ink-mute mb-1.5">Password</label>
          <div className="relative">
            <input type={show ? 'text' : 'password'} required value={form.password} onChange={e => setForm(f => ({ ...f, password: e.target.value }))}
              className={`${inputCls} pr-10`}
              placeholder="Min 8 characters" />
            <button type="button" onClick={() => setShow(s => !s)} aria-label={show ? 'Hide password' : 'Show password'} className="absolute right-3 top-1/2 -translate-y-1/2 text-ink-faint hover:text-ink-mute">
              {show ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
            </button>
          </div>
          <StrengthBar password={form.password} />
        </div>
        <div>
          <label className="block text-sm font-medium text-ink-mute mb-1.5">Confirm password</label>
          <input type="password" required value={form.confirm} onChange={e => setForm(f => ({ ...f, confirm: e.target.value }))}
            className={inputCls}
            placeholder="••••••••" />
        </div>
        <Button type="submit" size="lg" className="w-full justify-center" disabled={loading}>
          {loading ? 'Creating account…' : 'Create account'}
        </Button>
      </form>
      <p className="text-center text-sm text-ink-mute mt-6">
        Already have an account? <Link to="/login" className="text-primary font-medium hover:underline">Sign in</Link>
      </p>
    </AuthLayout>
  );
}

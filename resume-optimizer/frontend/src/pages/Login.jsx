import { useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { Eye, EyeOff } from 'lucide-react';
import toast from 'react-hot-toast';
import AuthLayout from '../components/layout/AuthLayout';
import Button from '../components/ui/Button';
import client from '../api/client';
import useAuthStore from '../store/authStore';

export default function Login() {
  const [form, setForm] = useState({ email: '', password: '' });
  const [show, setShow] = useState(false);
  const [loading, setLoading] = useState(false);
  const { login } = useAuthStore();
  const navigate = useNavigate();

  const submit = async (e) => {
    e.preventDefault();
    setLoading(true);
    try {
      const { data } = await client.post('/auth/login', form);
      login(data.access_token, data.user);
      navigate('/optimize');
    } catch (err) {
      toast.error(err.response?.data?.detail || 'Login failed');
    } finally {
      setLoading(false);
    }
  };

  return (
    <AuthLayout title="Welcome back" subtitle="Sign in to your account to continue">
      <form onSubmit={submit} className="space-y-5 page-fade">
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1.5">Email</label>
          <input type="email" required value={form.email} onChange={e => setForm(f => ({ ...f, email: e.target.value }))}
            className="w-full border border-gray-200 rounded-xl px-4 py-2.5 text-sm focus:outline-none focus:ring-2 focus:ring-primary/30 focus:border-primary transition-all"
            placeholder="you@example.com" />
        </div>
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1.5">Password</label>
          <div className="relative">
            <input type={show ? 'text' : 'password'} required value={form.password} onChange={e => setForm(f => ({ ...f, password: e.target.value }))}
              className="w-full border border-gray-200 rounded-xl px-4 py-2.5 pr-10 text-sm focus:outline-none focus:ring-2 focus:ring-primary/30 focus:border-primary transition-all"
              placeholder="••••••••" />
            <button type="button" onClick={() => setShow(s => !s)} className="absolute right-3 top-1/2 -translate-y-1/2 text-gray-400">
              {show ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
            </button>
          </div>
        </div>
        <Button type="submit" size="lg" className="w-full justify-center" disabled={loading}>
          {loading ? 'Signing in…' : 'Sign in'}
        </Button>
      </form>
      <p className="text-center text-sm text-gray-500 mt-6">
        Don't have an account? <Link to="/register" className="text-primary font-medium hover:underline">Create one</Link>
      </p>
    </AuthLayout>
  );
}

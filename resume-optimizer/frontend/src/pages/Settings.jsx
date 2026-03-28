import { useState } from 'react';
import { Link } from 'react-router-dom';
import toast from 'react-hot-toast';
import Sidebar from '../components/layout/Sidebar';
import Card from '../components/ui/Card';
import Button from '../components/ui/Button';
import Badge from '../components/ui/Badge';
import QuotaBar from '../components/ui/QuotaBar';
import client from '../api/client';
import useAuthStore from '../store/authStore';

export default function Settings() {
  const { user, logout } = useAuthStore();
  const [form, setForm] = useState({ full_name: user?.full_name || '', email: user?.email || '' });
  const [saving, setSaving] = useState(false);

  const save = async (e) => {
    e.preventDefault();
    setSaving(true);
    setTimeout(() => { toast.success('Profile updated'); setSaving(false); }, 800);
  };

  return (
    <div className="flex h-screen bg-surface overflow-hidden">
      <Sidebar />
      <main className="flex-1 overflow-y-auto">
        <div className="max-w-2xl mx-auto px-8 py-8 space-y-6">
          <h1 className="text-2xl font-bold text-gray-900">Settings</h1>

          {/* Profile */}
          <Card header="Profile">
            <form onSubmit={save} className="space-y-4">
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1.5">Full name</label>
                <input value={form.full_name} onChange={e => setForm(f => ({ ...f, full_name: e.target.value }))}
                  className="w-full border border-gray-200 rounded-xl px-4 py-2.5 text-sm focus:outline-none focus:ring-2 focus:ring-primary/30 focus:border-primary" />
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1.5">Email</label>
                <input value={form.email} type="email" onChange={e => setForm(f => ({ ...f, email: e.target.value }))}
                  className="w-full border border-gray-200 rounded-xl px-4 py-2.5 text-sm focus:outline-none focus:ring-2 focus:ring-primary/30 focus:border-primary" />
              </div>
              <Button type="submit" disabled={saving}>{saving ? 'Saving…' : 'Save changes'}</Button>
            </form>
          </Card>

          {/* Plan & Billing */}
          <Card header="Plan & Billing">
            <div className="flex items-center justify-between mb-4">
              <div>
                <div className="font-semibold text-gray-800 mb-1">Current plan</div>
                <Badge variant={user?.plan || 'free'} className="text-sm px-3 py-1">{user?.plan || 'free'}</Badge>
              </div>
              {user?.plan === 'free' && (
                <Button size="sm">Upgrade to Pro — $9/mo</Button>
              )}
            </div>
            <QuotaBar used={user?.limits?.daily_uploads || 0} total={user?.limits?.daily_uploads || 2} label="Daily uploads quota" />
          </Card>

          {/* Danger zone */}
          <Card header="Danger zone">
            <p className="text-sm text-gray-500 mb-4">Permanently delete your account and all data. This cannot be undone.</p>
            <Button variant="danger" size="sm" onClick={() => toast.error('Account deletion coming soon')}>Delete account</Button>
          </Card>
        </div>
      </main>
    </div>
  );
}

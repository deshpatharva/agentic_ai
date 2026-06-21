import { useEffect, useState } from 'react';
import toast from 'react-hot-toast';
import AppShell from '../components/layout/AppShell';
import Card from '../components/ui/Card';
import Button from '../components/ui/Button';
import Badge from '../components/ui/Badge';
import QuotaBar from '../components/ui/QuotaBar';
import client from '../api/client';
import useAuthStore from '../store/authStore';

const inputCls = 'w-full bg-card text-ink border border-line rounded-lg px-4 py-2.5 text-sm placeholder:text-ink-faint focus:outline-none focus:ring-2 focus:ring-primary/30 focus:border-primary transition-all';

export default function Settings() {
  const { user, logout, fetchMe } = useAuthStore();
  const [form, setForm] = useState({ full_name: user?.full_name || '', email: user?.email || '' });
  const [saving, setSaving] = useState(false);
  const [promoCode, setPromoCode] = useState('');
  const [promoLoading, setPromoLoading] = useState(false);
  const [promoMessage, setPromoMessage] = useState('');
  const [promoError, setPromoError] = useState('');
  const [quota, setQuota] = useState(null);

  useEffect(() => {
    client.get('/dashboard/summary')
      .then(r => setQuota({ used: r.data.today?.runs || 0, total: r.data.limits?.daily_uploads || 2 }))
      .catch(() => {});
  }, []);

  // Keep the form in sync with the user record once it hydrates / refreshes, so a
  // null-at-first-paint user can't lead to saving a blank name/email over the account.
  useEffect(() => {
    if (user) setForm({ full_name: user.full_name || '', email: user.email || '' });
  }, [user]);

  const save = async (e) => {
    e.preventDefault();
    setSaving(true);
    try {
      await client.put('/auth/me', form);
      await fetchMe();
      toast.success('Profile updated');
    } catch (err) {
      toast.error(err?.response?.data?.detail || 'Failed to save profile');
    } finally {
      setSaving(false);
    }
  };

  const handleRedeemCode = async () => {
    setPromoLoading(true);
    setPromoMessage('');
    setPromoError('');

    try {
      const response = await client.post('/user/redeem-promo-code', { code: promoCode });
      setPromoMessage(response.data.message);
      setPromoCode('');
      await fetchMe();
    } catch (err) {
      setPromoError(err?.response?.data?.detail || 'Failed to redeem code');
    } finally {
      setPromoLoading(false);
    }
  };

  return (
    <AppShell>
      <div className="page-fade">
        <div className="max-w-2xl mx-auto px-4 sm:px-8 py-8 space-y-6">
          <h1 className="font-display text-2xl font-semibold text-ink">Settings</h1>

          {/* Profile */}
          <Card header="Profile">
            <form onSubmit={save} className="space-y-4">
              <div>
                <label className="block text-sm font-medium text-ink-mute mb-1.5">Full name</label>
                <input value={form.full_name} onChange={e => setForm(f => ({ ...f, full_name: e.target.value }))}
                  className={inputCls} />
              </div>
              <div>
                <label className="block text-sm font-medium text-ink-mute mb-1.5">Email</label>
                <input value={form.email} type="email" onChange={e => setForm(f => ({ ...f, email: e.target.value }))}
                  className={inputCls} />
              </div>
              <Button type="submit" disabled={saving}>{saving ? 'Saving…' : 'Save changes'}</Button>
            </form>
          </Card>

          {/* Plan & Billing */}
          <Card header="Plan & Billing">
            <div className="flex items-center justify-between mb-4">
              <div>
                <div className="font-semibold text-ink mb-1">Current plan</div>
                <Badge variant={user?.plan || 'free'} className="text-sm px-3 py-1">{user?.plan || 'free'}</Badge>
              </div>
            </div>
            <QuotaBar used={quota?.used ?? 0} total={quota?.total ?? 2} label="Daily uploads quota" />
          </Card>

          {/* Redeem Promo Code */}
          <Card header="Redeem Promo Code">
            <div className="space-y-3">
              <div className="flex gap-2">
                <input
                  type="text"
                  placeholder="Enter promo code"
                  value={promoCode}
                  onChange={(e) => setPromoCode(e.target.value)}
                  className={`flex-1 ${inputCls}`}
                  disabled={promoLoading}
                />
                <Button
                  onClick={handleRedeemCode}
                  disabled={promoLoading || !promoCode}
                  size="sm"
                >
                  {promoLoading ? 'Redeeming...' : 'Redeem'}
                </Button>
              </div>
              {promoMessage && <div className="p-3 bg-accent-soft border border-primary/30 rounded-lg text-sm text-primary">{promoMessage}</div>}
              {promoError && <div className="p-3 bg-err-soft border border-err/30 rounded-lg text-sm text-err">{promoError}</div>}
            </div>
          </Card>

        </div>
      </div>
    </AppShell>
  );
}

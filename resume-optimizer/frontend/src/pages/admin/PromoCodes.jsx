import { useEffect, useState } from 'react';
import { Plus, X, Tag, Copy, Check } from 'lucide-react';
import toast from 'react-hot-toast';
import client from '../../api/client';

const TYPE_LABELS = {
  plan_upgrade:     'Plan Upgrade',
  trial_extension:  'Trial Extension',
  discount:         'Discount',
};

const STATUS_STYLES = {
  active:       'bg-accent-soft text-primary',
  expired:      'bg-hilite-soft text-hilite',
  deactivated:  'bg-surface-2 text-ink-faint',
};

const EMPTY_FORM = {
  code: '',
  type: 'plan_upgrade',
  target_plan: 'pro',
  days_to_add: '',
  discount_percent: '',
  max_uses: '',
  expires_at: '',
};

function CopyButton({ text }) {
  const [copied, setCopied] = useState(false);
  const copy = () => {
    navigator.clipboard.writeText(text);
    setCopied(true);
    setTimeout(() => setCopied(false), 1500);
  };
  return (
    <button onClick={copy} aria-label="Copy code" className="ml-1 text-ink-faint hover:text-ink-mute transition-colors">
      {copied ? <Check className="w-3 h-3 text-primary" /> : <Copy className="w-3 h-3" />}
    </button>
  );
}

export default function PromoCodes() {
  const [codes, setCodes]       = useState([]);
  const [total, setTotal]       = useState(0);
  const [loading, setLoading]   = useState(true);
  const [showForm, setShowForm] = useState(false);
  const [form, setForm]         = useState(EMPTY_FORM);
  const [saving, setSaving]     = useState(false);
  const [filter, setFilter]     = useState('');

  const fetchCodes = () => {
    setLoading(true);
    const params = new URLSearchParams({ limit: 100 });
    if (filter) params.set('status', filter);
    client.get(`/admin/promo-codes?${params}`)
      .then(r => { setCodes(r.data.codes); setTotal(r.data.total); })
      .catch(() => toast.error('Failed to load promo codes'))
      .finally(() => setLoading(false));
  };

  useEffect(() => { fetchCodes(); }, [filter]);

  const handleCreate = async (e) => {
    e.preventDefault();
    setSaving(true);
    try {
      const body = {
        code:     form.code.trim().toUpperCase(),
        type:     form.type,
        max_uses: parseInt(form.max_uses),
        ...(form.type === 'plan_upgrade'    && { target_plan:      form.target_plan }),
        ...(form.type === 'trial_extension' && { days_to_add:      parseInt(form.days_to_add) }),
        ...(form.type === 'discount'        && { discount_percent: parseInt(form.discount_percent) }),
        ...(form.expires_at && { expires_at: new Date(form.expires_at).toISOString() }),
      };
      await client.post('/admin/promo-codes', body);
      toast.success(`Promo code ${body.code} created`);
      setForm(EMPTY_FORM);
      setShowForm(false);
      fetchCodes();
    } catch (err) {
      toast.error(err.response?.data?.detail || 'Failed to create promo code');
    } finally {
      setSaving(false);
    }
  };

  const deactivate = async (id, code) => {
    if (!confirm(`Deactivate ${code}?`)) return;
    try {
      await client.patch(`/admin/promo-codes/${id}`);
      toast.success(`${code} deactivated`);
      fetchCodes();
    } catch (err) {
      toast.error(err.response?.data?.detail || 'Failed to deactivate');
    }
  };

  const field = (key) => ({
    value: form[key],
    onChange: (e) => setForm(f => ({ ...f, [key]: e.target.value })),
  });

  const inputCls = 'w-full bg-surface-2 border border-line rounded-lg px-3 py-2 text-sm text-ink placeholder:text-ink-faint focus:outline-none focus:border-primary';
  const labelCls = 'block text-xs text-ink-faint mb-1';

  return (
    <div className="p-4 sm:p-8">
      {/* Header */}
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-xl font-bold text-ink">Promo Codes</h1>
          <p className="text-xs text-ink-faint mt-0.5">{total} code{total !== 1 ? 's' : ''} total</p>
        </div>
        <button
          onClick={() => setShowForm(v => !v)}
          className="flex items-center gap-2 px-4 py-2 bg-primary hover:bg-primary-dark text-white dark:text-ink rounded-lg text-sm font-medium transition-colors"
        >
          {showForm ? <X className="w-4 h-4" /> : <Plus className="w-4 h-4" />}
          {showForm ? 'Cancel' : 'Create Code'}
        </button>
      </div>

      {/* Create form */}
      {showForm && (
        <form onSubmit={handleCreate} className="bg-card border border-line rounded-card p-6 mb-6 space-y-4">
          <p className="text-sm font-semibold text-ink mb-2">New Promo Code</p>

          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <div>
              <label className={labelCls}>Code *</label>
              <input {...field('code')} required placeholder="SUMMER25" className={inputCls}
                style={{ textTransform: 'uppercase' }} />
            </div>
            <div>
              <label className={labelCls}>Type *</label>
              <select {...field('type')} className={inputCls}>
                <option value="plan_upgrade">Plan Upgrade</option>
                <option value="trial_extension">Trial Extension</option>
                <option value="discount">Discount</option>
              </select>
            </div>
          </div>

          {/* Conditional fields */}
          {form.type === 'plan_upgrade' && (
            <div>
              <label className={labelCls}>Target Plan *</label>
              <select {...field('target_plan')} className={inputCls}>
                <option value="pro">Pro</option>
                <option value="enterprise">Enterprise</option>
              </select>
            </div>
          )}
          {form.type === 'trial_extension' && (
            <div>
              <label className={labelCls}>Days to Add *</label>
              <input {...field('days_to_add')} type="number" min="1" max="365" required
                placeholder="30" className={inputCls} />
            </div>
          )}
          {form.type === 'discount' && (
            <div>
              <label className={labelCls}>Discount % *</label>
              <input {...field('discount_percent')} type="number" min="1" max="100" required
                placeholder="20" className={inputCls} />
            </div>
          )}

          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <div>
              <label className={labelCls}>Max Uses *</label>
              <input {...field('max_uses')} type="number" min="1" required
                placeholder="100" className={inputCls} />
            </div>
            <div>
              <label className={labelCls}>Expires At (optional)</label>
              <input {...field('expires_at')} type="datetime-local" className={inputCls} />
            </div>
          </div>

          <button
            type="submit"
            disabled={saving}
            className="w-full py-2.5 bg-primary hover:bg-primary-dark disabled:opacity-50 text-white dark:text-ink rounded-lg text-sm font-medium transition-colors"
          >
            {saving ? 'Creating…' : 'Create Promo Code'}
          </button>
        </form>
      )}

      {/* Filters */}
      <div className="flex gap-2 mb-4">
        {['', 'active', 'expired', 'deactivated'].map(f => (
          <button key={f}
            onClick={() => setFilter(f)}
            className={`px-3 py-1.5 rounded-lg text-xs font-medium transition-colors ${
              filter === f
                ? 'bg-surface-2 text-ink'
                : 'text-ink-faint hover:text-ink-mute hover:bg-surface-2/60'
            }`}
          >
            {f === '' ? 'All' : f.charAt(0).toUpperCase() + f.slice(1)}
          </button>
        ))}
      </div>

      {/* Table */}
      <div className="bg-card border border-line rounded-card overflow-hidden">
        <div className="overflow-x-auto">
        <table className="w-full text-sm min-w-[720px]">
          <thead>
            <tr className="border-b border-line text-ink-faint text-xs uppercase tracking-wide">
              <th className="px-4 py-3 text-left">Code</th>
              <th className="px-4 py-3 text-left">Type</th>
              <th className="px-4 py-3 text-left">Details</th>
              <th className="px-4 py-3 text-left">Uses</th>
              <th className="px-4 py-3 text-left">Expires</th>
              <th className="px-4 py-3 text-left">Status</th>
              <th className="px-4 py-3 w-8" />
            </tr>
          </thead>
          <tbody>
            {loading ? (
              <tr><td colSpan={7} className="px-4 py-10 text-center text-ink-faint">Loading…</td></tr>
            ) : codes.length === 0 ? (
              <tr>
                <td colSpan={7} className="px-4 py-10 text-center text-ink-faint">
                  <Tag className="w-8 h-8 mx-auto mb-2 opacity-30" />
                  No promo codes yet
                </td>
              </tr>
            ) : codes.map(c => (
              <tr key={c.id} className="border-b border-line/60 hover:bg-surface-2/60 transition-colors">
                <td className="px-4 py-3">
                  <div className="flex items-center gap-1 font-mono text-ink text-xs font-semibold">
                    {c.code}
                    <CopyButton text={c.code} />
                  </div>
                </td>
                <td className="px-4 py-3 text-ink-mute text-xs">{TYPE_LABELS[c.type] || c.type}</td>
                <td className="px-4 py-3 text-ink-mute text-xs">
                  {c.type === 'plan_upgrade'    && `→ ${c.target_plan}`}
                  {c.type === 'trial_extension' && `+${c.days_to_add}d`}
                  {c.type === 'discount'        && `${c.discount_percent}% off`}
                </td>
                <td className="px-4 py-3 text-ink-mute text-xs">
                  {c.current_uses} / {c.max_uses}
                </td>
                <td className="px-4 py-3 text-ink-mute text-xs">
                  {c.expires_at
                    ? new Date(c.expires_at).toLocaleDateString()
                    : <span className="text-ink-faint">Never</span>}
                </td>
                <td className="px-4 py-3">
                  <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${STATUS_STYLES[c.status] || STATUS_STYLES.deactivated}`}>
                    {c.status}
                  </span>
                </td>
                <td className="px-4 py-3">
                  {c.status === 'active' && (
                    <button
                      onClick={() => deactivate(c.id, c.code)}
                      className="text-xs text-err hover:opacity-80 transition-colors"
                    >
                      Deactivate
                    </button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        </div>
      </div>
    </div>
  );
}

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
  active:       'bg-green-900 text-green-300',
  expired:      'bg-yellow-900 text-yellow-300',
  deactivated:  'bg-gray-800 text-gray-500',
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
    <button onClick={copy} className="ml-1 text-gray-600 hover:text-gray-300 transition-colors">
      {copied ? <Check className="w-3 h-3 text-green-400" /> : <Copy className="w-3 h-3" />}
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

  const inputCls = 'w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-sm text-white placeholder-gray-500 focus:outline-none focus:border-gray-500';
  const labelCls = 'block text-xs text-gray-500 mb-1';

  return (
    <div className="p-8">
      {/* Header */}
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-xl font-bold text-white">Promo Codes</h1>
          <p className="text-xs text-gray-500 mt-0.5">{total} code{total !== 1 ? 's' : ''} total</p>
        </div>
        <button
          onClick={() => setShowForm(v => !v)}
          className="flex items-center gap-2 px-4 py-2 bg-violet-600 hover:bg-violet-500 text-white rounded-lg text-sm font-medium transition-colors"
        >
          {showForm ? <X className="w-4 h-4" /> : <Plus className="w-4 h-4" />}
          {showForm ? 'Cancel' : 'Create Code'}
        </button>
      </div>

      {/* Create form */}
      {showForm && (
        <form onSubmit={handleCreate} className="bg-gray-900 border border-gray-800 rounded-xl p-6 mb-6 space-y-4">
          <p className="text-sm font-semibold text-white mb-2">New Promo Code</p>

          <div className="grid grid-cols-2 gap-4">
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

          <div className="grid grid-cols-2 gap-4">
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
            className="w-full py-2.5 bg-violet-600 hover:bg-violet-500 disabled:opacity-50 text-white rounded-lg text-sm font-medium transition-colors"
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
                ? 'bg-gray-700 text-white'
                : 'text-gray-500 hover:text-gray-300 hover:bg-gray-800'
            }`}
          >
            {f === '' ? 'All' : f.charAt(0).toUpperCase() + f.slice(1)}
          </button>
        ))}
      </div>

      {/* Table */}
      <div className="bg-gray-900 border border-gray-800 rounded-xl overflow-hidden">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-gray-800 text-gray-500 text-xs uppercase tracking-wide">
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
              <tr><td colSpan={7} className="px-4 py-10 text-center text-gray-600">Loading…</td></tr>
            ) : codes.length === 0 ? (
              <tr>
                <td colSpan={7} className="px-4 py-10 text-center text-gray-600">
                  <Tag className="w-8 h-8 mx-auto mb-2 opacity-30" />
                  No promo codes yet
                </td>
              </tr>
            ) : codes.map(c => (
              <tr key={c.id} className="border-b border-gray-800 hover:bg-gray-800/50 transition-colors">
                <td className="px-4 py-3">
                  <div className="flex items-center gap-1 font-mono text-white text-xs font-semibold">
                    {c.code}
                    <CopyButton text={c.code} />
                  </div>
                </td>
                <td className="px-4 py-3 text-gray-400 text-xs">{TYPE_LABELS[c.type] || c.type}</td>
                <td className="px-4 py-3 text-gray-400 text-xs">
                  {c.type === 'plan_upgrade'    && `→ ${c.target_plan}`}
                  {c.type === 'trial_extension' && `+${c.days_to_add}d`}
                  {c.type === 'discount'        && `${c.discount_percent}% off`}
                </td>
                <td className="px-4 py-3 text-gray-400 text-xs">
                  {c.current_uses} / {c.max_uses}
                </td>
                <td className="px-4 py-3 text-gray-400 text-xs">
                  {c.expires_at
                    ? new Date(c.expires_at).toLocaleDateString()
                    : <span className="text-gray-600">Never</span>}
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
                      className="text-xs text-red-500 hover:text-red-400 transition-colors"
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
  );
}

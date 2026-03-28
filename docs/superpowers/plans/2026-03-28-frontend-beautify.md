# Frontend Beautification Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Polish all 6 frontend screens (Landing, Auth, AppPage, Dashboard, JobMatches, Settings) with refined design tokens, component upgrades, and page-level improvements — no style overhaul, no new pages, no API changes.

**Architecture:** Component-first — upgrade the design system (tokens → components → layout → pages) so page improvements inherit automatically. All motion via Tailwind/CSS only (no animation library). 18 files total, all modifications.

**Tech Stack:** React 18, Vite, Tailwind CSS v3, clsx, lucide-react, react-router-dom

---

## File Map

| File | Change |
|------|--------|
| `frontend/tailwind.config.js` | Add shadow-card, shadow-lifted, shadow-primary tokens |
| `frontend/src/index.css` | Base transitions, route fade, custom scrollbar |
| `frontend/src/components/ui/Button.jsx` | Gradient primary, shadow-primary, rounded-xl, active:scale-95, focus ring |
| `frontend/src/components/ui/Card.jsx` | rounded-2xl, shadow-card, border-[#ebebeb], hover lift, structured header with divider |
| `frontend/src/components/ui/Badge.jsx` | font-semibold text-xs |
| `frontend/src/components/ui/QuotaBar.jsx` | Gradient fill, transition-[width] duration-500 |
| `frontend/src/components/ui/PipelineStep.jsx` | Full-row state design (done/running/pending colored rows + icon squares) |
| `frontend/src/components/ui/ScoreCard.jsx` | White card, gradient bar, status badge pill, animated fill via useEffect |
| `frontend/src/components/ui/CircularProgress.jsx` | Track color #f0f0f8, easing cubic-bezier(.4,0,.2,1) |
| `frontend/src/components/layout/Sidebar.jsx` | Left accent border, semi-transparent active bg, purple text |
| `frontend/src/components/layout/AuthLayout.jsx` | Dot-grid texture on left panel, feature cards hover transition |
| `frontend/src/pages/Landing.jsx` | "How it works" hero card between CTAs and features |
| `frontend/src/pages/AppPage.jsx` | Upload zone icon box (w-12 h-12 bg-violet-50), violet dashed border |
| `frontend/src/pages/Dashboard.jsx` | Stat card icon boxes with colored bg, table row hover |
| `frontend/src/pages/Login.jsx` | Verify transition-all on inputs (already present — confirm & add page-fade) |
| `frontend/src/pages/Register.jsx` | Verify transition-all on inputs (already present — confirm & add page-fade) |
| `frontend/src/pages/JobMatches.jsx` | Match score mini-bar on job cards, icon wrapper on upsell screen |
| `frontend/src/pages/Settings.jsx` | Input focus glow, page-fade |

---

### Task 1: Design Tokens

**Files:**
- Modify: `frontend/tailwind.config.js`
- Modify: `frontend/src/index.css`

- [ ] **Step 1: Add shadow tokens to tailwind.config.js**

Replace the existing file content:

```js
/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,jsx,ts,tsx}'],
  theme: {
    extend: {
      colors: {
        primary:        '#7F77DD',
        'primary-dark': '#534AB7',
        teal:           '#1D9E75',
        amber:          '#BA7517',
        surface:        '#FAFAF8',
        muted:          '#5F5E5A',
      },
      fontFamily: {
        sans: ['Inter', 'system-ui', 'sans-serif'],
      },
      boxShadow: {
        card:    '0 1px 3px rgba(0,0,0,.06), 0 4px 16px rgba(0,0,0,.04)',
        lifted:  '0 4px 16px rgba(0,0,0,.10), 0 1px 4px rgba(0,0,0,.06)',
        primary: '0 4px 12px rgba(127,119,221,.35)',
      },
      transitionDuration: {
        DEFAULT: '150ms',
      },
    },
  },
  plugins: [],
}
```

- [ ] **Step 2: Add base transitions, route fade, and custom scrollbar to index.css**

Replace the existing file content:

```css
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap');

@tailwind base;
@tailwind components;
@tailwind utilities;

* { box-sizing: border-box; }
body { font-family: 'Inter', system-ui, sans-serif; background: #FAFAF8; color: #1a1a1a; }

@layer base {
  button, a, input, textarea, select {
    transition: color 150ms ease, background-color 150ms ease, box-shadow 150ms ease, transform 150ms ease;
  }
}

.page-fade {
  animation: pageFade 150ms ease;
}
@keyframes pageFade {
  from { opacity: 0; }
  to   { opacity: 1; }
}

/* Custom scrollbar */
* {
  scrollbar-width: thin;
  scrollbar-color: #c4c3dc #e5e7eb;
}
::-webkit-scrollbar       { width: 6px; height: 6px; }
::-webkit-scrollbar-track  { background: #e5e7eb; border-radius: 99px; }
::-webkit-scrollbar-thumb  { background: #c4c3dc; border-radius: 99px; }
```

- [ ] **Step 3: Verify Tailwind picks up the new tokens**

Run: `cd resume-optimizer/frontend && npm run build 2>&1 | tail -5`

Expected: build completes with no errors (warnings about unused classes are fine)

- [ ] **Step 4: Commit**

```bash
git add resume-optimizer/frontend/tailwind.config.js resume-optimizer/frontend/src/index.css
git commit -m "feat(ui): add design tokens (shadow-card/lifted/primary, transitions, scrollbar, page-fade)"
```

---

### Task 2: Button Component

**Files:**
- Modify: `frontend/src/components/ui/Button.jsx`

- [ ] **Step 1: Update Button with gradient primary, shadow-primary, rounded-xl, active:scale-95, focus ring**

```jsx
import { clsx } from 'clsx';

const variants = {
  primary:   '[background:linear-gradient(135deg,#8b84e0,#7F77DD)] hover:opacity-90 text-white shadow-primary',
  secondary: 'bg-white hover:bg-gray-50 text-gray-700 border border-gray-200 shadow-card',
  ghost:     'bg-transparent hover:bg-gray-100 text-gray-600',
  danger:    'bg-red-600 hover:bg-red-700 text-white shadow-sm',
};
const sizes = {
  sm: 'px-3 py-1.5 text-sm rounded-xl',
  md: 'px-4 py-2 text-sm rounded-xl',
  lg: 'px-6 py-3 text-base rounded-xl',
};

export default function Button({ variant = 'primary', size = 'md', className, disabled, children, ...props }) {
  return (
    <button
      className={clsx(
        'font-semibold transition-all duration-150 inline-flex items-center gap-2 cursor-pointer',
        'active:scale-95',
        'focus-visible:ring-2 focus-visible:ring-primary/40 focus-visible:ring-offset-1 focus-visible:outline-none',
        variants[variant], sizes[size],
        disabled && 'opacity-50 cursor-not-allowed',
        className
      )}
      disabled={disabled}
      {...props}
    >
      {children}
    </button>
  );
}
```

- [ ] **Step 2: Commit**

```bash
git add resume-optimizer/frontend/src/components/ui/Button.jsx
git commit -m "feat(ui): Button — gradient primary, shadow-primary, rounded-xl, active:scale-95, focus ring"
```

---

### Task 3: Card Component

**Files:**
- Modify: `frontend/src/components/ui/Card.jsx`

- [ ] **Step 1: Update Card with rounded-2xl, shadow-card, border-[#ebebeb], hover lift, structured header**

```jsx
import { clsx } from 'clsx';

export default function Card({ children, className, header, footer }) {
  return (
    <div className={clsx(
      'bg-white rounded-2xl shadow-card border border-[#ebebeb]',
      'hover:-translate-y-0.5 hover:shadow-lifted transition-all duration-200',
      className
    )}>
      {header && (
        <div className="px-6 py-4 border-b border-gray-100 flex items-center justify-between">
          {typeof header === 'string'
            ? <span className="font-bold text-sm text-gray-900">{header}</span>
            : header}
        </div>
      )}
      <div className="p-6">{children}</div>
      {footer && (
        <div className="px-6 py-4 border-t border-gray-100 bg-gray-50 rounded-b-2xl">{footer}</div>
      )}
    </div>
  );
}
```

- [ ] **Step 2: Commit**

```bash
git add resume-optimizer/frontend/src/components/ui/Card.jsx
git commit -m "feat(ui): Card — rounded-2xl, shadow-card, border-[#ebebeb], hover lift, structured header"
```

---

### Task 4: Badge and QuotaBar Components

**Files:**
- Modify: `frontend/src/components/ui/Badge.jsx`
- Modify: `frontend/src/components/ui/QuotaBar.jsx`

- [ ] **Step 1: Update Badge with font-semibold and sharper variant colors**

```jsx
import { clsx } from 'clsx';

const styles = {
  free:       'bg-gray-100 text-gray-600',
  pro:        'bg-violet-100 text-violet-700',
  enterprise: 'bg-amber-100 text-amber-700',
  green:      'bg-green-100 text-green-700',
  amber:      'bg-amber-100 text-amber-700',
  red:        'bg-red-100 text-red-700',
  blue:       'bg-blue-100 text-blue-700',
  teal:       'bg-teal-100 text-teal-700',
};

export default function Badge({ variant = 'free', children, className }) {
  return (
    <span className={clsx(
      'inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-semibold',
      styles[variant],
      className
    )}>
      {children}
    </span>
  );
}
```

- [ ] **Step 2: Update QuotaBar with gradient fill and smooth transition**

```jsx
import { clsx } from 'clsx';

export default function QuotaBar({ used, total, label }) {
  const pct = total > 0 ? Math.min((used / total) * 100, 100) : 0;

  return (
    <div>
      {label && (
        <div className="flex justify-between text-xs text-gray-500 mb-1">
          <span>{label}</span>
          <span>{used} / {total}</span>
        </div>
      )}
      <div className="w-full h-2 bg-gray-100 rounded-full overflow-hidden">
        <div
          className="h-2 rounded-full transition-[width] duration-500 ease-out"
          style={{
            width: `${pct}%`,
            background: 'linear-gradient(90deg, #7F77DD, #a78bfa)',
          }}
        />
      </div>
    </div>
  );
}
```

- [ ] **Step 3: Commit**

```bash
git add resume-optimizer/frontend/src/components/ui/Badge.jsx resume-optimizer/frontend/src/components/ui/QuotaBar.jsx
git commit -m "feat(ui): Badge font-semibold sharper variants; QuotaBar gradient fill with transition"
```

---

### Task 5: PipelineStep Component

**Files:**
- Modify: `frontend/src/components/ui/PipelineStep.jsx`

- [ ] **Step 1: Replace dot+text design with full-width colored row design**

```jsx
import { clsx } from 'clsx';
import { Loader2 } from 'lucide-react';

const rowStyles = {
  done:    'bg-green-50',
  running: 'bg-violet-50',
  pending: '',
  error:   'bg-red-50',
};
const iconStyles = {
  done:    'bg-green-100',
  running: 'bg-violet-100',
  pending: 'bg-gray-100',
  error:   'bg-red-100',
};
const labelStyles = {
  done:    'text-green-700',
  running: 'text-violet-700',
  pending: 'text-gray-400',
  error:   'text-red-700',
};
const badgeStyles = {
  done:    'bg-green-100 text-green-700',
  running: 'bg-violet-100 text-violet-700',
  error:   'bg-red-100 text-red-700',
};
const iconContent = {
  done:    <span className="text-green-600 text-sm font-bold">✓</span>,
  running: <Loader2 className="w-3.5 h-3.5 text-violet-600 animate-spin" />,
  pending: null,
  error:   <span className="text-red-600 text-sm font-bold">✕</span>,
};
const badgeLabel = {
  done:    'Done',
  running: 'Running',
  error:   'Error',
};

export default function PipelineStep({ label, status = 'pending', sublabel }) {
  return (
    <div className={clsx(
      'flex items-center gap-3 px-3 py-2.5 rounded-xl transition-colors duration-200',
      rowStyles[status]
    )}>
      <div className={clsx(
        'w-7 h-7 rounded-lg flex items-center justify-center shrink-0',
        iconStyles[status]
      )}>
        {iconContent[status]}
      </div>
      <div className="flex-1 min-w-0">
        <div className={clsx('text-xs font-semibold', labelStyles[status])}>{label}</div>
        {sublabel && <div className="text-[10px] text-gray-400 mt-0.5">{sublabel}</div>}
      </div>
      {badgeLabel[status] && (
        <span className={clsx('text-[10px] font-semibold px-2 py-0.5 rounded-full', badgeStyles[status])}>
          {badgeLabel[status]}
        </span>
      )}
    </div>
  );
}
```

- [ ] **Step 2: Commit**

```bash
git add resume-optimizer/frontend/src/components/ui/PipelineStep.jsx
git commit -m "feat(ui): PipelineStep — colored row backgrounds, icon squares, status badge pills"
```

---

### Task 6: ScoreCard Component

**Files:**
- Modify: `frontend/src/components/ui/ScoreCard.jsx`

- [ ] **Step 1: Update ScoreCard with white card, gradient bar, status badge, animated fill on mount**

```jsx
import { clsx } from 'clsx';
import { useState, useEffect } from 'react';

function statusBadge(score) {
  if (score >= 85) return { label: 'Good',  cls: 'bg-green-100 text-green-700' };
  if (score >= 70) return { label: 'Fair',  cls: 'bg-amber-100 text-amber-700' };
  return                  { label: 'Low',   cls: 'bg-red-100 text-red-700' };
}

export default function ScoreCard({ label, score, items = [] }) {
  const [width, setWidth] = useState(0);
  const badge = statusBadge(score);

  useEffect(() => {
    // Start at 0 then animate to actual value on mount
    const id = requestAnimationFrame(() => setWidth(score));
    return () => cancelAnimationFrame(id);
  }, [score]);

  return (
    <div className="bg-white rounded-2xl border border-[#ebebeb] shadow-card p-4">
      <div className="flex items-start justify-between mb-1">
        <span className="text-[11px] font-semibold text-gray-500 tracking-wide uppercase">{label}</span>
        <span className={clsx('text-[11px] font-bold px-2 py-0.5 rounded-full', badge.cls)}>
          {badge.label}
        </span>
      </div>
      <div className="text-2xl font-extrabold text-gray-900 leading-none">{score}</div>
      <div className="text-[10px] text-gray-400 mt-0.5">/ 100</div>
      <div className="w-full h-1.5 bg-gray-100 rounded-full mt-3 overflow-hidden">
        <div
          className="h-1.5 rounded-full"
          style={{
            width: `${width}%`,
            background: 'linear-gradient(90deg, #7F77DD, #a78bfa)',
            transition: 'width 600ms cubic-bezier(.4,0,.2,1)',
          }}
        />
      </div>
      {items.length > 0 && (
        <ul className="mt-3 space-y-1">
          {items.slice(0, 3).map((item, i) => (
            <li key={i} className="text-xs text-gray-500 truncate">• {item}</li>
          ))}
        </ul>
      )}
    </div>
  );
}
```

- [ ] **Step 2: Commit**

```bash
git add resume-optimizer/frontend/src/components/ui/ScoreCard.jsx
git commit -m "feat(ui): ScoreCard — white card, gradient bar, status badge pill, animated fill on mount"
```

---

### Task 7: CircularProgress Component

**Files:**
- Modify: `frontend/src/components/ui/CircularProgress.jsx`

- [ ] **Step 1: Update track color to #f0f0f8 and easing to cubic-bezier(.4,0,.2,1)**

```jsx
export default function CircularProgress({ score, size = 120, strokeWidth = 10 }) {
  const r = (size - strokeWidth) / 2;
  const circ = 2 * Math.PI * r;
  const offset = circ - (score / 100) * circ;
  const color = score >= 85 ? '#1D9E75' : score >= 70 ? '#BA7517' : '#ef4444';

  return (
    <svg width={size} height={size} className="rotate-[-90deg]">
      <circle cx={size/2} cy={size/2} r={r} fill="none" stroke="#f0f0f8" strokeWidth={strokeWidth} />
      <circle
        cx={size/2} cy={size/2} r={r} fill="none"
        stroke={color} strokeWidth={strokeWidth}
        strokeDasharray={circ} strokeDashoffset={offset}
        strokeLinecap="round"
        style={{ transition: 'stroke-dashoffset 0.6s cubic-bezier(.4,0,.2,1)' }}
      />
      <text x="50%" y="50%" textAnchor="middle" dy="0.35em"
        fill={color}
        fontSize={size * 0.22} fontWeight="700"
        style={{ transform: 'rotate(90deg)', transformOrigin: 'center' }}
      >
        {score}
      </text>
    </svg>
  );
}
```

- [ ] **Step 2: Commit**

```bash
git add resume-optimizer/frontend/src/components/ui/CircularProgress.jsx
git commit -m "feat(ui): CircularProgress — purple-tinted track color, cubic-bezier easing"
```

---

### Task 8: Sidebar Layout Component

**Files:**
- Modify: `frontend/src/components/layout/Sidebar.jsx`

- [ ] **Step 1: Update active nav item to left accent border + semi-transparent bg, improve hover state**

Change only the nav link className logic (lines 36-45). Replace the active/inactive class strings:

```jsx
import { Link, useLocation, useNavigate } from 'react-router-dom';
import { LayoutDashboard, FileText, Briefcase, BarChart2, Settings, LogOut, Zap } from 'lucide-react';
import { clsx } from 'clsx';
import useAuthStore from '../../store/authStore';
import Badge from '../ui/Badge';

const nav = [
  { to: '/dashboard',         icon: LayoutDashboard, label: 'Overview' },
  { to: '/dashboard/resumes', icon: FileText,         label: 'My Resumes' },
  { to: '/dashboard/matches', icon: Briefcase,        label: 'Job Matches', proBadge: true },
  { to: '/dashboard/usage',   icon: BarChart2,        label: 'Usage' },
  { to: '/dashboard/settings',icon: Settings,         label: 'Settings' },
];

export default function Sidebar() {
  const location = useLocation();
  const navigate = useNavigate();
  const { user, logout } = useAuthStore();

  const handleLogout = () => { logout(); navigate('/login'); };
  const isPro = user?.plan === 'pro' || user?.plan === 'enterprise';

  return (
    <aside className="w-60 shrink-0 h-screen sticky top-0 bg-gray-900 text-white flex flex-col">
      <div className="px-6 py-5 border-b border-gray-800">
        <Link to="/dashboard" className="flex items-center gap-2">
          <Zap className="w-5 h-5 text-primary" />
          <span className="font-bold text-lg">ResumeAI</span>
        </Link>
      </div>

      <nav className="flex-1 px-3 py-4 space-y-1 overflow-y-auto">
        {nav.map(({ to, icon: Icon, label, proBadge }) => {
          const active = location.pathname === to || (to !== '/dashboard' && location.pathname.startsWith(to));
          return (
            <Link key={to} to={to}
              className={clsx(
                'flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm transition-all duration-150 border-l-2',
                active
                  ? 'border-primary bg-primary/10 text-primary'
                  : 'border-transparent text-gray-400 hover:bg-white/5 hover:text-white'
              )}>
              <Icon className="w-4 h-4 shrink-0" />
              <span className="flex-1">{label}</span>
              {proBadge && !isPro && <Badge variant="pro" className="text-[10px] px-1.5 py-0">Pro</Badge>}
            </Link>
          );
        })}
      </nav>

      <div className="px-4 py-4 border-t border-gray-800">
        {user?.plan === 'free' && (
          <Link to="/dashboard/settings"
            className="flex items-center gap-2 w-full bg-primary/10 hover:bg-primary/20 text-primary px-3 py-2.5 rounded-lg text-sm font-medium mb-3 transition-colors">
            <Zap className="w-4 h-4" />Upgrade to Pro
          </Link>
        )}
        <div className="flex items-center gap-3">
          <div className="w-8 h-8 rounded-full bg-primary/20 text-primary flex items-center justify-center text-sm font-bold shrink-0">
            {(user?.full_name || user?.email || 'U')[0].toUpperCase()}
          </div>
          <div className="flex-1 min-w-0">
            <div className="text-sm font-medium truncate">{user?.full_name || 'User'}</div>
            <Badge variant={user?.plan || 'free'} className="mt-0.5">{user?.plan || 'free'}</Badge>
          </div>
          <button onClick={handleLogout} className="text-gray-500 hover:text-white transition-colors">
            <LogOut className="w-4 h-4" />
          </button>
        </div>
      </div>
    </aside>
  );
}
```

- [ ] **Step 2: Commit**

```bash
git add resume-optimizer/frontend/src/components/layout/Sidebar.jsx
git commit -m "feat(ui): Sidebar — left accent border, semi-transparent active bg, purple text on active"
```

---

### Task 9: AuthLayout Component

**Files:**
- Modify: `frontend/src/components/layout/AuthLayout.jsx`

- [ ] **Step 1: Add dot-grid texture to left panel and hover transition to feature cards**

```jsx
import { Zap } from 'lucide-react';

export default function AuthLayout({ children, title, subtitle }) {
  return (
    <div className="min-h-screen flex">
      <div className="hidden lg:flex w-1/2 bg-gradient-to-br from-primary to-primary-dark flex-col justify-center px-16 text-white relative overflow-hidden">
        {/* Dot-grid texture overlay */}
        <div
          className="absolute inset-0 opacity-10 pointer-events-none"
          style={{
            backgroundImage: 'radial-gradient(circle, rgba(255,255,255,0.8) 1px, transparent 1px)',
            backgroundSize: '20px 20px',
          }}
        />
        <div className="relative z-10">
          <div className="flex items-center gap-3 mb-8">
            <Zap className="w-8 h-8" />
            <span className="text-2xl font-bold">ResumeAI</span>
          </div>
          <h2 className="text-4xl font-bold leading-tight mb-4">Your resume, optimized by AI</h2>
          <p className="text-purple-200 text-lg">Upload once. Score on 4 dimensions. Iterate until perfect. Get hired faster.</p>
          <div className="mt-12 grid grid-cols-2 gap-4">
            {[['4 AI Scorers','ATS, Impact, Skills, Structure'],['Smart Rewriter','Aligned to your exact JD'],['Job Matching','Nightly scrape of matched roles'],['Real-time Progress','Live pipeline status']].map(([t,d]) => (
              <div key={t} className="bg-white/10 backdrop-blur-sm rounded-xl p-4 hover:bg-white/15 transition-colors">
                <div className="font-semibold mb-1">{t}</div>
                <div className="text-purple-200 text-sm">{d}</div>
              </div>
            ))}
          </div>
        </div>
      </div>
      <div className="flex-1 flex flex-col justify-center px-8 lg:px-16 bg-white">
        <div className="max-w-md w-full mx-auto">
          <div className="flex items-center gap-2 mb-8 lg:hidden">
            <Zap className="w-6 h-6 text-primary" />
            <span className="text-xl font-bold">ResumeAI</span>
          </div>
          <h1 className="text-2xl font-bold text-gray-900 mb-2">{title}</h1>
          <p className="text-gray-500 mb-8">{subtitle}</p>
          {children}
        </div>
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Commit**

```bash
git add resume-optimizer/frontend/src/components/layout/AuthLayout.jsx
git commit -m "feat(ui): AuthLayout — dot-grid texture on left panel, feature card hover transitions"
```

---

### Task 10: Landing Page

**Files:**
- Modify: `frontend/src/pages/Landing.jsx`

- [ ] **Step 1: Add "How it works" card between CTAs and features, apply page-fade**

```jsx
import { Link } from 'react-router-dom';
import { Zap, Target, Briefcase, ArrowRight, Check } from 'lucide-react';
import TopNav from '../components/layout/TopNav';

const features = [
  { icon: Zap,      color: 'text-primary bg-purple-50',  title: 'AI Rewriter',    desc: 'Gemini 2.5 Flash rewrites your resume to align with every JD keyword.' },
  { icon: Target,   color: 'text-teal bg-teal-50',       title: 'Smart Scoring',  desc: '4 scorers: ATS match, impact, skills gap, and readability — all in one call.' },
  { icon: Briefcase,color: 'text-amber bg-amber-50',     title: 'Job Matching',   desc: 'Nightly scrape of matched roles from Adzuna, RemoteOK, and The Muse.' },
];

const plans = [
  { name: 'Free',       price: '$0',  period: '/mo', features: ['2 uploads / day','1 resume stored','4 AI scorers','PDF + DOCX export'],    highlight: false, plan: 'free' },
  { name: 'Pro',        price: '$9',  period: '/mo', features: ['20 uploads / day','10 resumes stored','Job matching','Usage history'],      highlight: true,  plan: 'pro' },
  { name: 'Enterprise', price: '$29', period: '/mo', features: ['Unlimited uploads','Unlimited storage','API access','Priority queue'],      highlight: false, plan: 'enterprise' },
];

const steps = [
  { n: '1', label: 'Upload',   desc: 'Drop PDF or DOCX' },
  { n: '2', label: 'Optimize', desc: 'AI rewrites resume', active: true },
  { n: '3', label: 'Download', desc: 'Get your .docx' },
];

export default function Landing() {
  return (
    <div className="min-h-screen bg-surface page-fade">
      <TopNav />

      {/* Hero */}
      <section className="max-w-5xl mx-auto px-6 py-24 text-center">
        <div className="inline-flex items-center gap-2 bg-purple-50 text-primary px-4 py-1.5 rounded-full text-sm font-medium mb-6">
          <Zap className="w-3.5 h-3.5" /> Powered by Gemini 2.5 + Claude
        </div>
        <h1 className="text-5xl lg:text-6xl font-bold text-gray-900 leading-tight mb-6">
          Your resume,<br /><span className="text-primary">optimized by AI</span>
        </h1>
        <p className="text-xl text-gray-500 mb-10 max-w-2xl mx-auto">
          Upload once. Score on 4 dimensions. Iterate until perfect. Get more interviews.
        </p>
        <div className="flex items-center justify-center gap-4">
          <Link to="/register" className="inline-flex items-center gap-2 px-8 py-3.5 rounded-xl font-semibold text-lg text-white shadow-primary transition-all active:scale-95"
            style={{ background: 'linear-gradient(135deg,#8b84e0,#7F77DD)' }}>
            Get started free <ArrowRight className="w-5 h-5" />
          </Link>
          <Link to="/app" className="text-gray-600 hover:text-gray-900 px-6 py-3.5 font-medium transition-colors">
            Try without account →
          </Link>
        </div>

        {/* How it works */}
        <div className="mt-14 bg-white rounded-2xl shadow-card border border-[#ebebeb] px-8 py-6 max-w-lg mx-auto">
          <p className="text-[10px] font-bold tracking-widest text-gray-400 uppercase mb-5">How it works</p>
          <div className="flex items-center justify-between">
            {steps.map((s, i) => (
              <div key={s.n} className="flex items-center flex-1">
                <div className="flex flex-col items-center flex-1">
                  <div className={`w-9 h-9 rounded-full flex items-center justify-center mb-2 font-bold text-sm border-2 ${
                    s.active
                      ? 'border-primary bg-primary text-white'
                      : 'border-primary text-primary bg-white'
                  }`}>
                    {s.n}
                  </div>
                  <div className="text-xs font-semibold text-gray-800">{s.label}</div>
                  <div className="text-[10px] text-gray-400 mt-0.5 text-center">{s.desc}</div>
                </div>
                {i < steps.length - 1 && (
                  <div className="h-px flex-1 mx-2 mb-6"
                    style={{ background: 'linear-gradient(90deg,#7F77DD,#a78bfa)', opacity: 0.4 }} />
                )}
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* Features */}
      <section className="max-w-5xl mx-auto px-6 pb-24">
        <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
          {features.map(({ icon: Icon, color, title, desc }) => (
            <div key={title} className="bg-white rounded-2xl p-6 shadow-card border border-[#ebebeb] hover:-translate-y-0.5 hover:shadow-lifted transition-all duration-200">
              <div className={`w-10 h-10 rounded-xl flex items-center justify-center mb-4 ${color}`}>
                <Icon className="w-5 h-5" />
              </div>
              <h3 className="font-semibold text-gray-900 mb-2">{title}</h3>
              <p className="text-gray-500 text-sm leading-relaxed">{desc}</p>
            </div>
          ))}
        </div>
      </section>

      {/* Pricing */}
      <section className="bg-gray-900 py-24">
        <div className="max-w-5xl mx-auto px-6">
          <h2 className="text-3xl font-bold text-white text-center mb-4">Simple, transparent pricing</h2>
          <p className="text-gray-400 text-center mb-12">Start free. Upgrade when you need more.</p>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-6 items-start">
            {plans.map(({ name, price, period, features, highlight }) => (
              <div key={name} className="flex flex-col">
                <div className="h-7 flex items-center justify-center mb-1">
                  {highlight && <span className="bg-amber-400 text-gray-900 text-xs font-bold px-3 py-1 rounded-full whitespace-nowrap">Most popular</span>}
                </div>
                <div className={`rounded-2xl p-8 ${highlight ? 'bg-primary ring-2 ring-primary/50 text-white' : 'bg-gray-800 text-gray-200'}`}>
                  <div className="font-semibold text-lg mb-1">{name}</div>
                  <div className="flex items-end gap-1 mb-6">
                    <span className="text-4xl font-bold">{price}</span>
                    <span className={`text-sm mb-1 ${highlight ? 'text-purple-200' : 'text-gray-400'}`}>{period}</span>
                  </div>
                  <ul className="space-y-3 mb-8">
                    {features.map(f => (
                      <li key={f} className="flex items-center gap-2 text-sm">
                        <Check className={`w-4 h-4 shrink-0 ${highlight ? 'text-white' : 'text-teal'}`} />{f}
                      </li>
                    ))}
                  </ul>
                  <Link to="/register" className={`block text-center py-2.5 rounded-xl font-medium text-sm transition-colors ${highlight ? 'bg-white text-primary hover:bg-purple-50' : 'bg-gray-700 hover:bg-gray-600 text-white'}`}>
                    Get started
                  </Link>
                </div>
              </div>
            ))}
          </div>
        </div>
      </section>
    </div>
  );
}
```

- [ ] **Step 2: Commit**

```bash
git add resume-optimizer/frontend/src/pages/Landing.jsx
git commit -m "feat(landing): add How it works hero card, gradient CTA, page-fade, updated feature cards"
```

---

### Task 11: AppPage

**Files:**
- Modify: `frontend/src/pages/AppPage.jsx`

- [ ] **Step 1: Update upload zone — add icon box, change dashed border to violet, add page-fade**

In `AppPage.jsx`, make the following targeted changes:

1. Add `page-fade` to the outermost `<div className="min-h-screen bg-surface">` → `<div className="min-h-screen bg-surface page-fade">`

2. Replace the empty-state inner div of the upload zone (lines 139-147) with an icon box above the text:

```jsx
) : (
  <div className="flex flex-col items-center gap-3">
    <div className="w-12 h-12 rounded-xl bg-violet-50 flex items-center justify-center">
      <Upload className="w-6 h-6 text-primary" />
    </div>
    <div>
      <p className="text-sm font-medium text-gray-700">Drop your resume here</p>
      <p className="text-xs text-gray-400 mt-1">or click to browse · PDF, DOCX</p>
    </div>
    <input type="file" accept=".pdf,.docx" className="hidden" onChange={handleDrop} id="file-in" />
    <label htmlFor="file-in" className="text-xs text-primary cursor-pointer underline">Browse file</label>
  </div>
)}
```

3. Update the upload zone border color: change `'border-gray-200 hover:border-primary/50'` to `'border-violet-200 hover:border-primary/50'`

The upload zone className becomes:
```jsx
className={`rounded-2xl border-2 border-dashed p-8 text-center cursor-pointer transition-all ${dragging ? 'border-primary bg-purple-50' : file ? 'border-green-400 bg-green-50' : 'border-violet-200 hover:border-primary/50'}`}
```

- [ ] **Step 2: Commit**

```bash
git add resume-optimizer/frontend/src/pages/AppPage.jsx
git commit -m "feat(apppage): upload zone icon box, violet dashed border, page-fade"
```

---

### Task 12: Dashboard

**Files:**
- Modify: `frontend/src/pages/Dashboard.jsx`

- [ ] **Step 1: Add colored icon boxes to stat cards and hover state to table rows**

1. Add `page-fade` to `<div className="flex h-screen bg-surface overflow-hidden">` → `<div className="flex h-screen bg-surface overflow-hidden page-fade">`

2. Replace the stats row map (the `.map(({ icon: Icon, label, value, color })` block) with icon boxes:

```jsx
{[
  { icon: TrendingUp, label: "Today's runs",      value: `${today.runs || 0} / ${limits.daily_uploads || 0}`, iconBg: 'bg-violet-50', iconColor: 'text-violet-500' },
  { icon: Target,     label: 'Best score',        value: stats.best_score || 0,                                iconBg: 'bg-green-50',  iconColor: 'text-green-500' },
  { icon: FileText,   label: 'Resumes optimized', value: stats.total_resumes || 0,                             iconBg: 'bg-violet-50', iconColor: 'text-violet-500' },
  { icon: Briefcase,  label: 'Unread matches',    value: stats.unread_matches || 0,                            iconBg: 'bg-amber-50',  iconColor: 'text-amber-500' },
].map(({ icon: Icon, label, value, iconBg, iconColor }) => (
  <Card key={label} className="!p-5">
    <div className={`w-9 h-9 rounded-xl flex items-center justify-center mb-3 ${iconBg}`}>
      <Icon className={`w-4 h-4 ${iconColor}`} />
    </div>
    <div className="text-2xl font-bold text-gray-900 mb-0.5">{value}</div>
    <div className="text-xs text-gray-500">{label}</div>
  </Card>
))}
```

3. Add hover state to table rows — change `<tr key={r.id}>` to `<tr key={r.id} className="hover:bg-gray-50 transition-colors">`

- [ ] **Step 2: Commit**

```bash
git add resume-optimizer/frontend/src/pages/Dashboard.jsx
git commit -m "feat(dashboard): stat card icon boxes, table row hover, page-fade"
```

---

### Task 13: Login and Register Pages

**Files:**
- Modify: `frontend/src/pages/Login.jsx`
- Modify: `frontend/src/pages/Register.jsx`

Both pages already have `focus:ring-2 focus:ring-primary/30 focus:border-primary transition-all` on all inputs. The only change needed is adding `page-fade` to the `<AuthLayout>` wrapper. Since `AuthLayout` renders `children` inside a flex container, add `page-fade` to the form's parent. The cleanest approach is wrapping the returned `<AuthLayout>` in a fragment and adding the class to a wrapping div, but AuthLayout already renders the white right panel — so instead add `page-fade` directly on the `<form>` tag in each page.

- [ ] **Step 1: Add page-fade to Login form**

In `Login.jsx`, change:
```jsx
<form onSubmit={submit} className="space-y-5">
```
to:
```jsx
<form onSubmit={submit} className="space-y-5 page-fade">
```

- [ ] **Step 2: Add page-fade to Register form**

In `Register.jsx`, change:
```jsx
<form onSubmit={submit} className="space-y-5">
```
to:
```jsx
<form onSubmit={submit} className="space-y-5 page-fade">
```

- [ ] **Step 3: Commit**

```bash
git add resume-optimizer/frontend/src/pages/Login.jsx resume-optimizer/frontend/src/pages/Register.jsx
git commit -m "feat(auth): add page-fade to Login and Register forms"
```

---

### Task 14: JobMatches Page

**Files:**
- Modify: `frontend/src/pages/JobMatches.jsx`

- [ ] **Step 1: Add match score mini-bar to job cards, icon wrapper on upsell screen, page-fade**

1. Add `page-fade` to both `<div className="flex h-screen bg-surface overflow-hidden">` divs (upsell screen and main screen).

2. Upsell screen — wrap the `<Lock>` icon with a styled box. Change:
```jsx
<Lock className="w-12 h-12 text-gray-300 mx-auto mb-4" />
```
to:
```jsx
<div className="bg-gray-100 p-4 rounded-2xl inline-flex items-center justify-center mb-4">
  <Lock className="w-10 h-10 text-gray-400" />
</div>
```

3. Job card — add match score mini-bar below the company name. After:
```jsx
<p className="text-sm text-gray-500 mb-2">{m.company || 'Company not listed'}</p>
```
add:
```jsx
{m.similarity_score != null && (
  <div className="flex items-center gap-2 mt-1 mb-2">
    <div className="flex-1 h-1.5 bg-gray-100 rounded-full overflow-hidden">
      <div
        className="h-1.5 rounded-full"
        style={{
          width: `${Math.round(m.similarity_score * 100)}%`,
          background: 'linear-gradient(90deg, #7F77DD, #a78bfa)',
        }}
      />
    </div>
    <span className="text-xs font-bold text-primary">
      {Math.round(m.similarity_score * 100)}%
    </span>
  </div>
)}
```

4. Remove the old percentage text from the badge row — change:
```jsx
{m.similarity_score != null && (
  <span className="text-xs text-gray-400">{Math.round(m.similarity_score * 100)}% match</span>
)}
```
to nothing (delete those 3 lines) since the score is now shown in the mini-bar.

Also update the outer `div` of each job card from:
```jsx
<div key={i} className="bg-white rounded-2xl border border-gray-100 p-5 shadow-sm flex items-start gap-4">
```
to use the design system tokens:
```jsx
<div key={i} className="bg-white rounded-2xl border border-[#ebebeb] p-5 shadow-card hover:-translate-y-0.5 hover:shadow-lifted transition-all duration-200 flex items-start gap-4">
```

- [ ] **Step 2: Commit**

```bash
git add resume-optimizer/frontend/src/pages/JobMatches.jsx
git commit -m "feat(jobmatches): match score mini-bar, upsell icon wrapper, hover lift, page-fade"
```

---

### Task 15: Settings Page

**Files:**
- Modify: `frontend/src/pages/Settings.jsx`

- [ ] **Step 1: Add input focus glow and page-fade**

1. Add `page-fade` to `<div className="flex h-screen bg-surface overflow-hidden">` → `<div className="flex h-screen bg-surface overflow-hidden page-fade">`

2. Both inputs in the Profile card are missing `transition-all` and focus glow. Update their `className`:

```jsx
className="w-full border border-gray-200 rounded-xl px-4 py-2.5 text-sm focus:outline-none focus:ring-2 focus:ring-primary/30 focus:border-primary transition-all duration-150 focus:shadow-[0_0_0_3px_rgba(127,119,221,.15)]"
```

Apply this className to both the "Full name" and "Email" inputs in the Profile card.

- [ ] **Step 2: Commit**

```bash
git add resume-optimizer/frontend/src/pages/Settings.jsx
git commit -m "feat(settings): input focus glow, transition-all on profile inputs, page-fade"
```

---

## Self-Review

**Spec coverage check:**

| Spec requirement | Task |
|------------------|------|
| shadow-card / shadow-lifted / shadow-primary tokens | Task 1 |
| Base transitions on interactive elements | Task 1 |
| Route fade (.page-fade) | Task 1 + Tasks 10-15 |
| Custom scrollbar | Task 1 |
| Button gradient, shadow-primary, rounded-xl, active:scale-95, focus ring | Task 2 |
| Card rounded-2xl, shadow-card, border-[#ebebeb], hover lift, structured header | Task 3 |
| Badge font-semibold, sharper variant colors | Task 4 |
| QuotaBar gradient fill, transition-[width] | Task 4 |
| PipelineStep full-row colored design | Task 5 |
| ScoreCard white card, gradient bar, status badge, animated fill | Task 6 |
| CircularProgress track color #f0f0f8, easing update | Task 7 |
| Sidebar left accent border, semi-transparent active | Task 8 |
| AuthLayout dot-grid texture, feature card hover | Task 9 |
| Landing "How it works" card | Task 10 |
| AppPage upload zone icon box, violet border | Task 11 |
| Dashboard stat icon boxes, table row hover | Task 12 |
| Login/Register input focus consistency | Task 13 |
| JobMatches score mini-bar, upsell icon wrapper | Task 14 |
| Settings input focus glow | Task 15 |

All 18 spec files covered. No dark mode, no new pages, no API changes — all out of scope correctly excluded.

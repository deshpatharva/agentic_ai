import { useEffect, useState } from 'react';
import { NavLink, Outlet, Link, useLocation } from 'react-router-dom';
import { LayoutDashboard, Users, BarChart2, Tag, ArrowLeft, Activity, ShieldCheck, Menu, X } from 'lucide-react';
import useAuthStore from '../../store/authStore';

const navItems = [
  { to: '/admin',              end: true,  icon: LayoutDashboard, label: 'Overview' },
  { to: '/admin/runs',         end: false, icon: Activity,        label: 'Pipeline Runs' },
  { to: '/admin/users',        end: false, icon: Users,           label: 'Users' },
  { to: '/admin/promo-codes',  end: false, icon: Tag,             label: 'Promo Codes' },
  { to: '/admin/analytics',    end: false, icon: BarChart2,       label: 'Analytics' },
  { to: '/admin/observability', end: false, icon: Activity,       label: 'AI Observability' },
];

function AdminNav({ user }) {
  return (
    <div className="h-full bg-card border-r border-line flex flex-col">
      <div className="px-4 py-5 border-b border-line">
        <Link
          to="/dashboard"
          className="flex items-center gap-1.5 text-xs text-ink-faint hover:text-ink transition-colors mb-3"
        >
          <ArrowLeft className="w-3 h-3" /> Back to app
        </Link>
        <p className="flex items-center gap-1.5 text-xs font-bold tracking-widest text-hilite uppercase">
          <ShieldCheck className="w-3.5 h-3.5" /> Admin
        </p>
        <p className="text-xs text-ink-faint mt-0.5 truncate">{user?.email}</p>
      </div>
      <nav className="flex-1 p-3 space-y-1">
        {navItems.map(({ to, end, icon: Icon, label }) => (
          <NavLink
            key={to}
            to={to}
            end={end}
            className={({ isActive }) =>
              `flex items-center gap-2.5 px-3 py-2 rounded-lg text-sm transition-colors border-l-2 ${
                isActive
                  ? 'border-hilite bg-hilite/10 text-hilite'
                  : 'border-transparent text-ink-mute hover:text-ink hover:bg-surface-2'
              }`
            }
          >
            <Icon className="w-4 h-4" />
            {label}
          </NavLink>
        ))}
      </nav>
    </div>
  );
}

/* The `dark` class scopes the Manila & Ink dark tokens to the whole admin
   surface — admin is always ink, independent of the user's theme choice. */
export default function AdminLayout() {
  const { user } = useAuthStore();
  const [drawerOpen, setDrawerOpen] = useState(false);
  const location = useLocation();

  useEffect(() => { setDrawerOpen(false); }, [location.pathname]);
  useEffect(() => {
    if (!drawerOpen) return;
    const onKey = (e) => e.key === 'Escape' && setDrawerOpen(false);
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [drawerOpen]);

  return (
    <div className="dark">
      <div className="min-h-screen bg-surface text-ink flex">
        {/* Desktop sidebar */}
        <aside className="hidden lg:block w-56 shrink-0 sticky top-0 h-screen">
          <AdminNav user={user} />
        </aside>

        {/* Mobile top bar */}
        <header className="lg:hidden fixed top-0 inset-x-0 z-30 h-14 bg-card border-b border-line flex items-center gap-3 px-4">
          <button
            onClick={() => setDrawerOpen(true)}
            aria-label="Open admin navigation"
            className="p-2 -ml-2 rounded-lg text-ink-mute hover:bg-surface-2 transition-colors"
          >
            <Menu className="w-5 h-5" />
          </button>
          <p className="flex items-center gap-1.5 text-xs font-bold tracking-widest text-hilite uppercase">
            <ShieldCheck className="w-3.5 h-3.5" /> Admin
          </p>
        </header>

        {/* Mobile drawer */}
        {drawerOpen && (
          <div className="lg:hidden fixed inset-0 z-40">
            <div className="absolute inset-0 bg-black/60" onClick={() => setDrawerOpen(false)} aria-hidden="true" />
            <div className="absolute inset-y-0 left-0 w-64 shadow-lifted">
              <AdminNav user={user} />
              <button
                onClick={() => setDrawerOpen(false)}
                aria-label="Close admin navigation"
                className="absolute top-4 right-3 p-2 rounded-lg text-ink-faint hover:text-ink hover:bg-surface-2 transition-colors"
              >
                <X className="w-4 h-4" />
              </button>
            </div>
          </div>
        )}

        {/* Page content */}
        <main className="flex-1 min-w-0 overflow-auto pt-14 lg:pt-0">
          <Outlet />
        </main>
      </div>
    </div>
  );
}

import { Link, useLocation, useNavigate } from 'react-router-dom';
import { LayoutDashboard, FileText, Briefcase, BarChart2, Settings, LogOut, Zap, ShieldCheck, User } from 'lucide-react';
import { clsx } from 'clsx';
import useAuthStore from '../../store/authStore';
import Badge from '../ui/Badge';
import TrialBanner from '../TrialBanner';

const nav = [
  { to: '/optimize',          icon: Zap,             label: 'Optimize' },
  { to: '/dashboard',         icon: LayoutDashboard, label: 'Overview' },
  { to: '/profiles',          icon: User,            label: 'Profiles' },
  { to: '/dashboard/resumes', icon: FileText,         label: 'My Resumes' },
  { to: '/dashboard/matches', icon: Briefcase,        label: 'Job Matches', proBadge: true },
  { to: '/dashboard/usage',   icon: BarChart2,        label: 'Usage' },
  { to: '/dashboard/settings',icon: Settings,         label: 'Settings' },
];

const adminNav = [
  { to: '/admin',            icon: ShieldCheck, label: 'Admin' },
];

export default function Sidebar() {
  const location = useLocation();
  const navigate = useNavigate();
  const { user, logout } = useAuthStore();

  const handleLogout = () => { logout(); navigate('/login'); };
  const isPro = user?.plan === 'pro' || user?.plan === 'enterprise';
  const isAdmin = user?.is_admin === true;

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
        {isAdmin && (
          <>
            <div className="pt-3 pb-1 px-3 text-[10px] font-semibold uppercase tracking-widest text-gray-600">Admin</div>
            {adminNav.map(({ to, icon: Icon, label }) => {
              const active = location.pathname === to || location.pathname.startsWith(to + '/');
              return (
                <Link key={to} to={to}
                  className={clsx(
                    'flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm transition-all duration-150 border-l-2',
                    active
                      ? 'border-amber-400 bg-amber-400/10 text-amber-400'
                      : 'border-transparent text-gray-400 hover:bg-white/5 hover:text-white'
                  )}>
                  <Icon className="w-4 h-4 shrink-0" />
                  <span className="flex-1">{label}</span>
                </Link>
              );
            })}
          </>
        )}
      </nav>

      <div className="px-4 py-4 border-t border-gray-800">
        <TrialBanner />
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
            <Badge variant={isAdmin ? 'admin' : (user?.plan || 'free')} className="mt-0.5">
              {isAdmin ? 'admin' : (user?.plan || 'free')}
            </Badge>
          </div>
          <button onClick={handleLogout} className="text-gray-500 hover:text-white transition-colors">
            <LogOut className="w-4 h-4" />
          </button>
        </div>
      </div>
    </aside>
  );
}

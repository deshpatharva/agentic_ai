import { Link, useLocation, useNavigate } from 'react-router-dom';
import { LayoutDashboard, FileText, Briefcase, Settings, LogOut, Zap, ShieldCheck, User, Feather } from 'lucide-react';
import { clsx } from 'clsx';
import useAuthStore from '../../store/authStore';
import Badge from '../ui/Badge';
import ThemeToggle from '../ui/ThemeToggle';
import TrialBanner from '../TrialBanner';

const nav = [
  { to: '/optimize',          icon: Zap,             label: 'Optimize' },
  { to: '/dashboard',         icon: LayoutDashboard, label: 'Overview' },
  { to: '/profiles',          icon: User,            label: 'Profiles' },
  { to: '/dashboard/resumes', icon: FileText,         label: 'My Resumes' },
  { to: '/dashboard/matches', icon: Briefcase,        label: 'Job Matches', proBadge: true },
  { to: '/dashboard/settings',icon: Settings,         label: 'Settings' },
];

const adminNav = [
  { to: '/admin',            icon: ShieldCheck, label: 'Admin' },
];

/* The sidebar is a fixed "book spine": warm ink in both themes, so colors are
   literal rather than tokenized. Accent values match the dark-theme palette.
   SidebarContent is shared by the desktop aside and the mobile drawer. */
export function SidebarContent() {
  const location = useLocation();
  const navigate = useNavigate();
  const { user, logout } = useAuthStore();

  const handleLogout = () => { logout(); navigate('/login'); };
  const isPro = user?.plan === 'pro' || user?.plan === 'enterprise';
  const isAdmin = user?.is_admin === true;

  // Single source of truth for identity rendering — avatar and name share the same fallback chain.
  const displayName = user?.full_name?.trim() || user?.email?.split('@')[0] || 'User';
  const initial = (user?.full_name?.trim() || user?.email || 'U')[0].toUpperCase();

  return (
    <div className="h-full bg-[#171A1F] text-[#E9ECF0] flex flex-col">
      <div className="px-6 py-5 border-b border-[#262A30]">
        <Link to="/dashboard" className="flex items-center gap-2">
          <Feather className="w-5 h-5 text-[#2DD4BF]" />
          <span className="font-display font-semibold text-lg tracking-tight">ResumeAI</span>
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
                  ? 'border-[#2DD4BF] bg-[#2DD4BF]/10 text-[#2DD4BF]'
                  : 'border-transparent text-[#9AA1AA] hover:bg-white/5 hover:text-[#E9ECF0]'
              )}>
              <Icon className="w-4 h-4 shrink-0" />
              <span className="flex-1">{label}</span>
              {proBadge && !isPro && <Badge variant="pro" className="text-[10px] px-1.5 py-0">Pro</Badge>}
            </Link>
          );
        })}
        {isAdmin && (
          <>
            <div className="pt-3 pb-1 px-3 text-[10px] font-semibold uppercase tracking-widest text-[#6A7078]">Admin</div>
            {adminNav.map(({ to, icon: Icon, label }) => {
              const active = location.pathname === to || location.pathname.startsWith(to + '/');
              return (
                <Link key={to} to={to}
                  className={clsx(
                    'flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm transition-all duration-150 border-l-2',
                    active
                      ? 'border-[#EAB308] bg-[#EAB308]/10 text-[#EAB308]'
                      : 'border-transparent text-[#9AA1AA] hover:bg-white/5 hover:text-[#E9ECF0]'
                  )}>
                  <Icon className="w-4 h-4 shrink-0" />
                  <span className="flex-1">{label}</span>
                </Link>
              );
            })}
          </>
        )}
      </nav>

      <div className="px-4 py-4 border-t border-[#262A30]">
        <TrialBanner />
        {user?.plan === 'free' && (
          <Link to="/dashboard/settings"
            className="flex items-center gap-2 w-full bg-[#2DD4BF]/10 hover:bg-[#2DD4BF]/20 text-[#2DD4BF] px-3 py-2.5 rounded-lg text-sm font-medium mb-3 transition-colors">
            <Zap className="w-4 h-4" />Upgrade to Pro
          </Link>
        )}
        <div className="flex items-center gap-2">
          <div className="w-8 h-8 rounded-full bg-[#2DD4BF]/20 text-[#2DD4BF] flex items-center justify-center text-sm font-bold shrink-0">
            {initial}
          </div>
          <div className="flex-1 min-w-0">
            <div className="text-sm font-medium truncate">{displayName}</div>
            <Badge variant={isAdmin ? 'admin' : (user?.plan || 'free')} className="mt-0.5">
              {isAdmin ? 'admin' : (user?.plan || 'free')}
            </Badge>
          </div>
          <ThemeToggle className="text-[#6A7078] hover:text-[#E9ECF0] hover:bg-white/5" />
          <button onClick={handleLogout} aria-label="Log out" className="p-2 rounded-lg text-[#6A7078] hover:text-[#E9ECF0] hover:bg-white/5 transition-colors">
            <LogOut className="w-4 h-4" />
          </button>
        </div>
      </div>
    </div>
  );
}

/** Desktop-only sidebar. On mobile, AppShell renders the drawer instead. */
export default function Sidebar() {
  return (
    <aside className="hidden lg:block w-60 shrink-0 h-screen sticky top-0">
      <SidebarContent />
    </aside>
  );
}

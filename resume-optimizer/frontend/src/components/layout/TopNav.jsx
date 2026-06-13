import { Link, useNavigate } from 'react-router-dom';
import { Feather, LogOut, LayoutDashboard } from 'lucide-react';
import useAuthStore from '../../store/authStore';
import Badge from '../ui/Badge';
import ThemeToggle from '../ui/ThemeToggle';

export default function TopNav() {
  const { user, logout } = useAuthStore();
  const navigate = useNavigate();
  return (
    <header className="h-16 bg-card/80 backdrop-blur border-b border-line flex items-center px-4 sm:px-6 gap-3 sm:gap-4 sticky top-0 z-10">
      <Link to="/" className="flex items-center gap-2 font-display font-semibold text-lg text-ink tracking-tight">
        <Feather className="w-5 h-5 text-primary" />ResumeAI
      </Link>
      <div className="flex-1" />
      <ThemeToggle className="text-ink-faint hover:text-ink hover:bg-surface-2" />
      {user ? (
        <>
          <Link to="/dashboard" className="flex items-center gap-1.5 text-sm text-ink-mute hover:text-primary transition-colors">
            <LayoutDashboard className="w-4 h-4" />Dashboard
          </Link>
          <Badge variant={user.plan}>{user.plan}</Badge>
          <button onClick={() => { logout(); navigate('/login'); }} aria-label="Log out" className="text-ink-faint hover:text-ink">
            <LogOut className="w-4 h-4" />
          </button>
        </>
      ) : (
        <>
          <Link to="/login" className="hidden sm:block text-sm text-ink-mute hover:text-primary transition-colors">Sign in</Link>
          <Link to="/register" className="bg-primary text-white dark:text-ink px-4 py-1.5 rounded-lg text-sm font-medium hover:bg-primary-dark transition-colors whitespace-nowrap">Get started</Link>
        </>
      )}
    </header>
  );
}

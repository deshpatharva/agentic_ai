import { Link, useNavigate } from 'react-router-dom';
import { Zap, LogOut, LayoutDashboard } from 'lucide-react';
import useAuthStore from '../../store/authStore';
import Badge from '../ui/Badge';

export default function TopNav() {
  const { user, logout } = useAuthStore();
  const navigate = useNavigate();
  return (
    <header className="h-16 bg-white border-b border-gray-100 flex items-center px-6 gap-4 sticky top-0 z-10">
      <Link to="/" className="flex items-center gap-2 font-bold text-gray-800">
        <Zap className="w-5 h-5 text-primary" />ResumeAI
      </Link>
      <div className="flex-1" />
      {user ? (
        <>
          <Link to="/dashboard" className="flex items-center gap-1.5 text-sm text-gray-600 hover:text-primary transition-colors">
            <LayoutDashboard className="w-4 h-4" />Dashboard
          </Link>
          <Badge variant={user.plan}>{user.plan}</Badge>
          <button onClick={() => { logout(); navigate('/login'); }} className="text-gray-400 hover:text-gray-700">
            <LogOut className="w-4 h-4" />
          </button>
        </>
      ) : (
        <>
          <Link to="/login" className="text-sm text-gray-600 hover:text-primary transition-colors">Sign in</Link>
          <Link to="/register" className="bg-primary text-white px-4 py-1.5 rounded-lg text-sm font-medium hover:bg-primary-dark transition-colors">Get started</Link>
        </>
      )}
    </header>
  );
}

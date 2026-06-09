import { NavLink, Outlet, Link } from 'react-router-dom';
import { LayoutDashboard, Users, BarChart2, Tag, ArrowLeft } from 'lucide-react';
import useAuthStore from '../../store/authStore';

const navItems = [
  { to: '/admin',              end: true,  icon: LayoutDashboard, label: 'Dashboard' },
  { to: '/admin/users',        end: false, icon: Users,           label: 'Users' },
  { to: '/admin/promo-codes',  end: false, icon: Tag,             label: 'Promo Codes' },
  { to: '/admin/analytics',    end: false, icon: BarChart2,       label: 'Analytics' },
];

export default function AdminLayout() {
  const { user } = useAuthStore();

  return (
    <div className="min-h-screen bg-gray-950 flex">
      {/* Sidebar */}
      <aside className="w-56 bg-gray-900 border-r border-gray-800 flex flex-col shrink-0">
        <div className="px-4 py-5 border-b border-gray-800">
          <Link
            to="/dashboard"
            className="flex items-center gap-1.5 text-xs text-gray-500 hover:text-gray-300 transition-colors mb-3"
          >
            <ArrowLeft className="w-3 h-3" /> Back to app
          </Link>
          <p className="text-xs font-bold tracking-widest text-red-400 uppercase">Admin</p>
          <p className="text-xs text-gray-500 mt-0.5 truncate">{user?.email}</p>
        </div>
        <nav className="flex-1 p-3 space-y-1">
          {navItems.map(({ to, end, icon: Icon, label }) => (
            <NavLink
              key={to}
              to={to}
              end={end}
              className={({ isActive }) =>
                `flex items-center gap-2.5 px-3 py-2 rounded-lg text-sm transition-colors ${
                  isActive
                    ? 'bg-gray-800 text-white'
                    : 'text-gray-400 hover:text-white hover:bg-gray-800'
                }`
              }
            >
              <Icon className="w-4 h-4" />
              {label}
            </NavLink>
          ))}
        </nav>
      </aside>

      {/* Page content */}
      <main className="flex-1 overflow-auto">
        <Outlet />
      </main>
    </div>
  );
}

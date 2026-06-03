import { NavLink, Outlet } from 'react-router-dom';
import { LayoutDashboard, Users } from 'lucide-react';
import useAuthStore from '../../store/authStore';

export default function AdminLayout() {
  const { user } = useAuthStore();

  return (
    <div className="min-h-screen bg-gray-950 flex">
      {/* Sidebar */}
      <aside className="w-56 bg-gray-900 border-r border-gray-800 flex flex-col shrink-0">
        <div className="px-4 py-5 border-b border-gray-800">
          <p className="text-xs font-bold tracking-widest text-red-400 uppercase">Admin</p>
          <p className="text-xs text-gray-500 mt-0.5 truncate">{user?.email}</p>
        </div>
        <nav className="flex-1 p-3 space-y-1">
          <NavLink
            to="/admin"
            end
            className={({ isActive }) =>
              `flex items-center gap-2.5 px-3 py-2 rounded-lg text-sm transition-colors ${
                isActive
                  ? 'bg-gray-800 text-white'
                  : 'text-gray-400 hover:text-white hover:bg-gray-800'
              }`
            }
          >
            <LayoutDashboard className="w-4 h-4" />
            Dashboard
          </NavLink>
          <NavLink
            to="/admin/users"
            className={({ isActive }) =>
              `flex items-center gap-2.5 px-3 py-2 rounded-lg text-sm transition-colors ${
                isActive
                  ? 'bg-gray-800 text-white'
                  : 'text-gray-400 hover:text-white hover:bg-gray-800'
              }`
            }
          >
            <Users className="w-4 h-4" />
            Users
          </NavLink>
        </nav>
      </aside>

      {/* Page content */}
      <main className="flex-1 overflow-auto">
        <Outlet />
      </main>
    </div>
  );
}

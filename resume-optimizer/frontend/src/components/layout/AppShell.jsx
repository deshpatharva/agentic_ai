import { useEffect, useState } from 'react';
import { Link, useLocation } from 'react-router-dom';
import { Menu, X, Feather } from 'lucide-react';
import Sidebar, { SidebarContent } from './Sidebar';
import useAuthStore from '../../store/authStore';

// Refresh the cached user once per app load (AppShell remounts on every
// route change, so this lives at module scope).
let meRefreshed = false;

/**
 * Authenticated app frame: desktop sidebar (≥ lg) or mobile top bar with a
 * slide-over drawer (< lg). Pages with their own scroll management (chat)
 * pass scroll={false} and lay out inside a flex column.
 */
export default function AppShell({ children, scroll = true }) {
  const [drawerOpen, setDrawerOpen] = useState(false);
  const location = useLocation();
  const fetchMe = useAuthStore((s) => s.fetchMe);

  useEffect(() => {
    if (meRefreshed) return;
    meRefreshed = true;
    fetchMe();
  }, [fetchMe]);

  // Close the drawer on navigation and on Escape.
  useEffect(() => { setDrawerOpen(false); }, [location.pathname]);
  useEffect(() => {
    if (!drawerOpen) return;
    const onKey = (e) => e.key === 'Escape' && setDrawerOpen(false);
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [drawerOpen]);

  return (
    <div className="flex h-screen bg-surface overflow-hidden">
      <Sidebar />

      {/* Mobile top bar */}
      <header className="lg:hidden fixed top-0 inset-x-0 z-30 h-14 bg-[#171A1F] text-[#E9ECF0] flex items-center gap-3 px-4">
        <button
          onClick={() => setDrawerOpen(true)}
          aria-label="Open navigation"
          className="p-2 -ml-2 rounded-lg hover:bg-white/5 transition-colors"
        >
          <Menu className="w-5 h-5" />
        </button>
        <Link to="/dashboard" className="flex items-center gap-2">
          <Feather className="w-4 h-4 text-[#2DD4BF]" />
          <span className="font-display font-semibold tracking-tight">ResumeAI</span>
        </Link>
      </header>

      {/* Mobile drawer */}
      {drawerOpen && (
        <div className="lg:hidden fixed inset-0 z-40">
          <div
            className="absolute inset-0 bg-black/50"
            onClick={() => setDrawerOpen(false)}
            aria-hidden="true"
          />
          <div className="absolute inset-y-0 left-0 w-64 shadow-lifted">
            <SidebarContent />
            <button
              onClick={() => setDrawerOpen(false)}
              aria-label="Close navigation"
              className="absolute top-4 right-3 p-2 rounded-lg text-[#6A7078] hover:text-[#E9ECF0] hover:bg-white/5 transition-colors"
            >
              <X className="w-4 h-4" />
            </button>
          </div>
        </div>
      )}

      <main className={`flex-1 min-w-0 pt-14 lg:pt-0 ${scroll ? 'overflow-y-auto' : 'overflow-hidden flex flex-col'}`}>
        {children}
      </main>
    </div>
  );
}

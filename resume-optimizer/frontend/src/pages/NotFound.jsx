import { Link } from 'react-router-dom';
import { Feather } from 'lucide-react';
import useAuthStore from '../store/authStore';

export default function NotFound() {
  const { token } = useAuthStore();

  return (
    <div className="min-h-screen bg-surface flex flex-col items-center justify-center px-6 text-center page-fade">
      <Feather className="w-8 h-8 text-primary mb-6" />
      <h1 className="font-display text-6xl font-semibold text-ink mb-3">404</h1>
      <p className="text-ink-mute mb-8 max-w-sm">
        This page doesn't exist — like a typo on a résumé, best quietly corrected.
      </p>
      <Link
        to={token ? '/optimize' : '/'}
        className="bg-primary hover:bg-primary-dark text-white dark:text-surface px-6 py-2.5 rounded-lg text-sm font-semibold shadow-primary transition-colors"
      >
        {token ? 'Back to Optimize' : 'Back to home'}
      </Link>
    </div>
  );
}

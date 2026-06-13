import { Sun, Moon } from 'lucide-react';
import { clsx } from 'clsx';
import useTheme from '../../theme';

export default function ThemeToggle({ className }) {
  const { isDark, toggle } = useTheme();

  return (
    <button
      type="button"
      onClick={toggle}
      aria-label={isDark ? 'Switch to light mode' : 'Switch to dark mode'}
      title={isDark ? 'Light mode' : 'Dark mode'}
      className={clsx(
        'p-2 rounded-lg transition-colors',
        'focus-visible:ring-2 focus-visible:ring-primary/40 focus-visible:outline-none',
        className
      )}
    >
      {isDark ? <Sun className="w-4 h-4" /> : <Moon className="w-4 h-4" />}
    </button>
  );
}

import { useEffect, useState } from 'react';

const media = window.matchMedia('(prefers-color-scheme: dark)');

function resolveDark() {
  const stored = localStorage.getItem('theme');
  return stored === 'dark' || (!stored && media.matches);
}

/**
 * Theme state: explicit user choice persisted in localStorage('theme'),
 * otherwise follows the OS. The <html>.dark class is the source of truth
 * (set pre-paint by the inline script in index.html).
 */
export default function useTheme() {
  const [isDark, setIsDark] = useState(() => document.documentElement.classList.contains('dark'));

  useEffect(() => {
    // follow OS changes only while the user hasn't made an explicit choice
    const onChange = () => {
      if (localStorage.getItem('theme')) return;
      const dark = resolveDark();
      document.documentElement.classList.toggle('dark', dark);
      setIsDark(dark);
    };
    media.addEventListener('change', onChange);
    return () => media.removeEventListener('change', onChange);
  }, []);

  const toggle = () => {
    const next = !isDark;
    localStorage.setItem('theme', next ? 'dark' : 'light');
    document.documentElement.classList.toggle('dark', next);
    setIsDark(next);
  };

  return { isDark, toggle };
}

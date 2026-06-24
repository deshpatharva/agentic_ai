/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,jsx,ts,tsx}'],
  darkMode: 'class',
  theme: {
    extend: {
      colors: {
        // Manila & Ink semantic tokens — values live in src/index.css
        surface:         'rgb(var(--c-bg) / <alpha-value>)',        // page background
        card:            'rgb(var(--c-surface) / <alpha-value>)',   // raised surfaces
        'surface-2':     'rgb(var(--c-surface-2) / <alpha-value>)', // subtle fills, hovers
        ink:             'rgb(var(--c-ink) / <alpha-value>)',
        'ink-mute':      'rgb(var(--c-ink-mute) / <alpha-value>)',
        'ink-faint':     'rgb(var(--c-ink-faint) / <alpha-value>)',
        line:            'rgb(var(--c-line) / <alpha-value>)',
        primary:         'rgb(var(--c-accent) / <alpha-value>)',
        'primary-dark':  'rgb(var(--c-accent-strong) / <alpha-value>)',
        'accent-soft':   'rgb(var(--c-accent-soft) / <alpha-value>)',
        hilite:          'rgb(var(--c-hilite) / <alpha-value>)',
        'hilite-soft':   'rgb(var(--c-hilite-soft) / <alpha-value>)',
        err:             'rgb(var(--c-err) / <alpha-value>)',
        'err-soft':      'rgb(var(--c-err-soft) / <alpha-value>)',
        // legacy aliases (pre-revamp class names still in use)
        teal:            'rgb(var(--c-accent) / <alpha-value>)',
        amber:           'rgb(var(--c-hilite) / <alpha-value>)',
        muted:           'rgb(var(--c-ink-mute) / <alpha-value>)',
      },
      fontFamily: {
        sans:    ['Inter', 'system-ui', 'sans-serif'],
        display: ['"Space Grotesk"', 'system-ui', 'sans-serif'],
        mono:    ['"JetBrains Mono"', 'ui-monospace', 'monospace'],
      },
      borderRadius: {
        // instrument: crisp panels, no pills on containers
        DEFAULT: '6px',
        card: '8px',
      },
      boxShadow: {
        card:    'var(--shadow-card)',
        lifted:  'var(--shadow-lifted)',
        primary: 'var(--shadow-accent)',
      },
      transitionDuration: {
        DEFAULT: '150ms',
      },
    },
  },
  plugins: [],
}

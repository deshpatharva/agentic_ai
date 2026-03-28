/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,jsx,ts,tsx}'],
  theme: {
    extend: {
      colors: {
        primary:        '#7F77DD',
        'primary-dark': '#534AB7',
        teal:           '#1D9E75',
        amber:          '#BA7517',
        surface:        '#FAFAF8',
        muted:          '#5F5E5A',
      },
      fontFamily: {
        sans: ['Inter', 'system-ui', 'sans-serif'],
      },
      boxShadow: {
        card:    '0 1px 3px rgba(0,0,0,.06), 0 4px 16px rgba(0,0,0,.04)',
        lifted:  '0 4px 16px rgba(0,0,0,.10), 0 1px 4px rgba(0,0,0,.06)',
        primary: '0 4px 12px rgba(127,119,221,.35)',
      },
      transitionDuration: {
        DEFAULT: '150ms',
      },
    },
  },
  plugins: [],
}

/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,jsx,ts,tsx}'],
  theme: {
    extend: {
      colors: {
        primary:      '#7F77DD',
        'primary-dark': '#534AB7',
        teal:         '#1D9E75',
        amber:        '#BA7517',
        surface:      '#FAFAF8',
        muted:        '#5F5E5A',
      },
      fontFamily: {
        sans: ['Inter', 'system-ui', 'sans-serif'],
      },
    },
  },
  plugins: [],
}

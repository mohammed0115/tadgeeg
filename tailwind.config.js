/** @type {import('tailwindcss').Config} */
module.exports = {
  darkMode: 'class',
  content: [
    './templates/**/*.html',
    './apps/**/templates/**/*.html',
    './static/src/js/**/*.js',
  ],
  theme: {
    extend: {
      colors: {
        // Single source of truth — matches static/src/css/tokens.css
        primary: {
          50:  '#e6f0fa',
          100: '#cce0f5',
          200: '#99c1eb',
          300: '#66a3e0',
          400: '#3366a3',
          500: '#003366',   // Saudi navy — corporate
          600: '#002b57',
          700: '#002244',
          800: '#001a33',
          900: '#001122',
        },
        accent: {
          50:  '#ecfdf5',
          100: '#d1fae5',
          200: '#a7f3d0',
          300: '#6ee7b7',
          400: '#34d399',
          500: '#10b981',   // Saudi green — success
          600: '#059669',
          700: '#047857',
          800: '#065f46',
          900: '#064e3b',
        },
        danger: {
          500: '#ef4444',
          600: '#dc2626',
          700: '#b91c1c',
        },
        warning: {
          500: '#f59e0b',
          600: '#d97706',
        },
      },
      fontFamily: {
        sans:    ['Tajawal', 'Cairo', 'Inter', 'system-ui', 'Arial', 'sans-serif'],
        display: ['Cairo', 'Tajawal', 'Inter', 'system-ui', 'sans-serif'],
        mono:    ['Consolas', 'Courier New', 'monospace'],
      },
      borderRadius: {
        'xl':  '0.75rem',
        '2xl': '1rem',
        '3xl': '1.5rem',
      },
      boxShadow: {
        'card':    '0 1px 2px 0 rgb(0 51 102 / 0.05)',
        'card-md': '0 4px 14px -2px rgb(0 51 102 / 0.08)',
        'card-lg': '0 14px 28px -10px rgb(0 51 102 / 0.14)',
      },
    },
  },
  plugins: [
    // Logical properties (margin-inline-start, etc.) — required for RTL.
    require('postcss-logical'),
  ],
};

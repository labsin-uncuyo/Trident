/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,ts,jsx,tsx}'],
  darkMode: 'class',
  theme: {
    extend: {
      colors: {
        trident: {
          // Light mode colors - MAXIMUM contrast
          bg: '#f1f5f9',
          surface: '#ffffff',
          border: '#cbd5e1',
          'border-hover': '#94a3b8',
          accent: '#1d4ed8',
          'accent-hover': '#1e40af',
          success: '#166534',
          warning: '#92400e',
          danger: '#991b1b',
          muted: '#1e293b',
          text: '#020617',
          'text-secondary': '#1e293b',
        },
      },
      fontFamily: {
        sans: ['Inter', 'system-ui', 'sans-serif'],
        heading: ['Montserrat', 'system-ui', 'sans-serif'],
        mono: ['JetBrains Mono', 'Fira Code', 'monospace'],
      },
    },
  },
  plugins: [
    // Plugin to add dark mode color overrides
    function({ addVariant }) {
      addVariant('dark', '.dark &');
    },
  ],
};

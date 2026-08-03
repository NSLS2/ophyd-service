/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  corePlugins: {
    // finch.css already ships Tailwind's Preflight reset globally
    // (imported in entry-client.tsx), so we disable ours to avoid duplication.
    preflight: false,
  },
  theme: {
    extend: {
      colors: {
        brand: {
          teal: '#105c78',
          cyan: '#00addc',
          red: '#e50000',
          navy: '#1a1a2e',
          slate: '#1f2937',
        },
        panel: {
          border: '#d6dde1',
          muted: '#9ca3af',
        },
      },
      maxWidth: {
        app: '120rem', // 1920px page container cap for large displays
      },
      keyframes: {
        'fade-in': {
          '0%': { opacity: '0', transform: 'translateY(-10px)' },
          '100%': { opacity: '1', transform: 'translateY(0)' },
        },
        'fade-out': {
          '0%': { opacity: '1', transform: 'translateY(0)' },
          '100%': { opacity: '0', transform: 'translateY(-10px)' },
        },
      },
      animation: {
        'fade-in': 'fade-in 0.3s ease-out',
        'fade-out': 'fade-out 0.3s ease-out',
      },
    },
  },
  plugins: [],
}

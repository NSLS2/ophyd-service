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
        app: '90rem', // 1440px page container cap
      },
    },
  },
  plugins: [],
}

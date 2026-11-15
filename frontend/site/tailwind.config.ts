import type { Config } from 'tailwindcss'

const config: Config = {
  content: ['./app/**/*.{js,ts,jsx,tsx,mdx}', './components/**/*.{js,ts,jsx,tsx,mdx}'],
  theme: {
    extend: {
      colors: {
        background: 'var(--background)', surface: 'var(--surface)', border: 'var(--border)',
        accent: '#2476ff', glow: '#76c5ff', highlight: '#4aa3ff',
        foreground: '#f2f8ff', muted: '#a4bad3', success: '#3fb68b',
      },
      borderRadius: { card: '12px', pill: '999px' },
      fontFamily: {
        sans: ['var(--font-inter)', 'sans-serif'],
        display: ['var(--font-space)', 'sans-serif'],
        mono: ['var(--font-mono)', 'monospace'],
      },
      boxShadow: { glow: '0 0 50px rgba(36, 118, 255, .25)' },
    },
  },
  plugins: [],
}

export default config

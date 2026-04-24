/**
 * Enkidu v10 — Matrix design tokens
 * Phosphor green on deep black. Digital rain aesthetic.
 */
/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        // Surface
        bg:        '#000800',
        surface:   '#010a01',
        elevated:  '#021402',
        sunken:    '#000600',
        border:    '#0a2a0a',
        'border-strong': '#1a5a1a',
        // Foreground
        fg:        '#80ff9a',
        muted:     '#3d7a4a',
        subtle:    '#1a3a20',
        // Accents — Matrix green replaces amber
        amber:     { DEFAULT: '#00ff41', soft: '#00ff4118', dim: '#006618', glow: '#00ff4145' },
        // Matrix teal replaces cyan
        cyan:      { DEFAULT: '#00ffcc', soft: '#00ffcc14', dim: '#00664a', glow: '#00ffcc38' },
        // Success — neon green
        emerald:   { DEFAULT: '#00ff41', soft: '#00ff4118', dim: '#006618' },
        // Error — red stays
        rose:      { DEFAULT: '#ff4444', soft: '#ff44441a', dim: '#7a1a1a' },
        // Dev/code special
        violet:    { DEFAULT: '#00f5d4', soft: '#00f5d41a' },
      },
      fontFamily: {
        mono:    ['"JetBrains Mono"', '"Fira Code"', '"Share Tech Mono"', 'ui-monospace', 'monospace'],
        display: ['"Space Grotesk"', '"Inter"', 'system-ui', 'sans-serif'],
        retro:   ['"VT323"', '"Share Tech Mono"', 'monospace'],
      },
      fontSize: {
        '2xs': ['10px', { lineHeight: '1.4', letterSpacing: '0.06em' }],
        xs:    ['11px', { lineHeight: '1.45' }],
        sm:    ['12.5px', { lineHeight: '1.5' }],
        base:  ['13.5px', { lineHeight: '1.55' }],
        md:    ['14.5px', { lineHeight: '1.55' }],
        lg:    ['16px',   { lineHeight: '1.45' }],
        xl:    ['18px',   { lineHeight: '1.35' }],
        '2xl': ['22px',   { lineHeight: '1.25' }],
        '3xl': ['28px',   { lineHeight: '1.2'  }],
      },
      spacing: {
        px: '1px',
        0.5: '2px',
      },
      boxShadow: {
        glow:        '0 0 12px var(--tw-shadow-color)',
        'glow-sm':   '0 0 6px var(--tw-shadow-color)',
        'glow-lg':   '0 0 24px var(--tw-shadow-color)',
        panel:       '0 0 0 1px #0a2a0a, 0 1px 0 0 rgba(0,255,65,0.04) inset',
        'panel-hi':  '0 0 0 1px #1a5a1a, 0 0 24px -8px rgba(0,255,65,0.20)',
      },
      borderRadius: {
        none: '0',
        sm:   '2px',
        DEFAULT: '3px',
        md:   '4px',
        lg:   '6px',
      },
      animation: {
        'pulse-soft': 'pulse-soft 2.4s ease-in-out infinite',
        'pulse-fast': 'pulse-fast 0.7s ease-in-out infinite',
        'scan':       'scan 6s linear infinite',
        'shimmer':    'shimmer 2.5s linear infinite',
        'matrix-drip':'matrix-drip 4s linear infinite',
      },
      keyframes: {
        'pulse-soft':  { '0%,100%': { opacity: 1 }, '50%': { opacity: 0.45 } },
        'pulse-fast':  { '0%,100%': { opacity: 1 }, '50%': { opacity: 0.3 } },
        'scan':        { '0%': { transform: 'translateY(-100%)' }, '100%': { transform: 'translateY(100%)' } },
        'shimmer':     { '0%': { backgroundPosition: '-200% 0' }, '100%': { backgroundPosition: '200% 0' } },
        'matrix-drip': {
          '0%':   { opacity: 0, transform: 'translateY(-8px)' },
          '10%':  { opacity: 1 },
          '90%':  { opacity: 1 },
          '100%': { opacity: 0, transform: 'translateY(8px)' },
        },
      },
    },
  },
  plugins: [],
}

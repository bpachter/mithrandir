/**
 * Mithrandir — Ancient Gold & Mithril Silver design tokens
 * Dark stone base, antique gold primary, mithril silver secondary.
 */
/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        // Surfaces
        bg:        '#0d0b09',
        surface:   '#12100d',
        elevated:  '#1c1914',
        sunken:    '#080706',
        border:    '#241f16',
        'border-strong': '#362e20',
        // Foreground
        fg:        '#d4cfc0',
        muted:     '#7a7060',
        subtle:    '#3d3628',
        // Primary antique gold
        amber:     { DEFAULT: '#d4af37', soft: '#d4af3712', dim: '#3d2c08', glow: '#d4af3720' },
        // Mithril silver
        cyan:      { DEFAULT: '#a8bcd8', soft: '#a8bcd810', dim: '#1e2a3d', glow: '#a8bcd820' },
        // Success green
        emerald:   { DEFAULT: '#4ade80', soft: '#4ade8012', dim: '#166534' },
        // Error red
        rose:      { DEFAULT: '#f87171', soft: '#f871711a', dim: '#7f1d1d' },
        // Accent violet
        violet:    { DEFAULT: '#a78bfa', soft: '#a78bfa1a' },
      },
      fontFamily: {
        mono:    ['"JetBrains Mono"', 'ui-monospace', 'monospace'],
        display: ['"Inter"', 'system-ui', 'sans-serif'],
        retro:   ['"JetBrains Mono"', 'ui-monospace', 'monospace'],
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
        sm:         '0 1px 3px rgba(0,0,0,0.45)',
        DEFAULT:    '0 2px 8px rgba(0,0,0,0.5), 0 1px 2px rgba(0,0,0,0.4)',
        md:         '0 4px 16px rgba(0,0,0,0.55), 0 2px 4px rgba(0,0,0,0.4)',
        lg:         '0 8px 28px rgba(0,0,0,0.6), 0 4px 8px rgba(0,0,0,0.4)',
        panel:      '0 0 0 1px #241f16',
        'panel-hi': '0 0 0 1px #362e20, 0 4px 16px -4px rgba(212,175,55,0.18)',
      },
      borderRadius: {
        none: '0',
        sm:   '3px',
        DEFAULT: '5px',
        md:   '7px',
        lg:   '10px',
        full: '9999px',
      },
      animation: {
        'pulse-soft': 'pulse-soft 2.4s ease-in-out infinite',
        'pulse-fast': 'pulse-fast 0.7s ease-in-out infinite',
        'shimmer':    'shimmer 2.5s linear infinite',
      },
      keyframes: {
        'pulse-soft': { '0%,100%': { opacity: 1 }, '50%': { opacity: 0.45 } },
        'pulse-fast': { '0%,100%': { opacity: 1 }, '50%': { opacity: 0.35 } },
        'shimmer':    { '0%': { backgroundPosition: '-200% 0' }, '100%': { backgroundPosition: '200% 0' } },
      },
    },
  },
  plugins: [],
}

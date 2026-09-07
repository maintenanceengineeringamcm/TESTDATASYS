/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,ts,jsx,tsx}'],
  theme: {
    extend: {
      colors: {
        // Light-blue / white palette. Text stays near-black for contrast.
        brand: {
          50: '#F2F8FE',
          100: '#E3F0FC',
          200: '#C7E1F8',
          300: '#9BCBF2',
          400: '#63ADE9',
          500: '#2E8FDD',
          600: '#1E72BC',
          700: '#195B96',
          800: '#174B79',
          900: '#163F64',
        },
        ink: {
          DEFAULT: '#0B1220',
          soft: '#334155',
          muted: '#64748B',
          faint: '#94A3B8',
        },
        line: '#DCE7F3',

        // Deep surfaces for the sidebar and header. These are chrome, not data,
        // so they stay in the neutral-blue family and never borrow a status hue.
        navy: {
          700: '#1A4272',
          800: '#123252',
          900: '#0C2138',
          950: '#08172A',
        },

        // Category accents. Identity colours for the three transformer
        // populations, deliberately chosen clear of the green/amber/red status
        // scale so an inventory tile can never be misread as a condition.
        // Validated all-pairs on both the white card and the tinted page:
        // CVD dE 13.0, normal-vision dE 16.3, all >= 3:1 contrast.
        accent: {
          tr: '#2A78D6',      // power transformers  - categorical slot 1
          aet: '#4A3AA7',     // earthing/auxiliary  - categorical slot 7
          oltc: '#D55181',    // tap changers        - categorical slot 5
          neutral: '#5A6B80',
        },
      },
      fontFamily: {
        sans: ['Inter', 'Segoe UI', 'system-ui', 'sans-serif'],
        mono: ['JetBrains Mono', 'Consolas', 'monospace'],
      },
      boxShadow: {
        card: '0 1px 2px rgba(16,42,67,0.05), 0 4px 16px rgba(16,42,67,0.06)',
        pop: '0 8px 30px rgba(16,42,67,0.12)',
      },
      borderRadius: {
        xl: '0.875rem',
      },
    },
  },
  plugins: [],
}

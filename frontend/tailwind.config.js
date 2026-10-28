/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        clay: {
          50: '#FFF3E6',
          100: '#FFEDD5',
          200: '#FED7AA',
          300: '#FDBA74',
          400: '#FB923C',
          500: '#F97316',
          600: '#EA580C',
          700: '#C2410C',
          800: '#9A3412',
          900: '#7C2D12',
          950: '#431407',
        },
        gold: {
          50: '#FFFBEB',
          100: '#FEF3C7',
          200: '#FDE68A',
          300: '#FCD34D',
          400: '#FBBF24',
          500: '#F59E0B',
          600: '#D97706',
          700: '#B45309',
        },
        cream: '#FFF9F2',
        sand: '#F6EBDD',
        paper: '#FFFDF8',
        ink: '#291007',
        cocoa: {
          100: '#F1E8DF',
          300: '#C4A88F',
          500: '#8A6A52',
          800: '#4A2310',
          900: '#3B1B0B',
          950: '#291007',
        },
      },
      fontFamily: {
        display: ['Lalezar', 'Cairo', 'sans-serif'],
        heading: ['Cairo', 'Tajawal', 'sans-serif'],
        sans: ['Tajawal', 'Cairo', 'sans-serif'],
        code: ['"JetBrains Mono"', 'monospace'],
      },
      boxShadow: {
        warm: '0 14px 40px -14px rgba(74,35,16,0.22)',
        pop: '0 20px 50px -18px rgba(124,45,18,0.35)',
      },
    },
  },
  plugins: [],
};

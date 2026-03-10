/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        'cyan': {
          DEFAULT: '#0891b2',
          dim: '#0e7490',
          glow: 'rgba(8, 145, 178, 0.2)',
        },
        'purple': {
          DEFAULT: '#6f61f1',
          dim: '#5b50d6',
          glow: 'rgba(111, 97, 241, 0.15)',
        },
        'success': '#16a34a',
        'warning': '#d97706',
        'danger': '#dc2626',
        'base': '#f5f5f5',
        'card': '#ffffff',
        'elevated': '#f0f0f0',
        'hover': '#e5e5e5',
        'primary': '#1a1a2e',
        'secondary': '#5f6368',
        'muted': '#9aa0a6',
        'border': {
          dim: 'rgba(0, 0, 0, 0.06)',
          DEFAULT: 'rgba(0, 0, 0, 0.1)',
          accent: 'rgba(8, 145, 178, 0.3)',
          purple: 'rgba(111, 97, 241, 0.3)',
        },
      },
      backgroundImage: {
        'gradient-purple-cyan': 'linear-gradient(135deg, rgba(111, 97, 241, 0.15) 0%, rgba(8, 145, 178, 0.08) 100%)',
        'gradient-card-border': 'linear-gradient(180deg, rgba(111, 97, 241, 0.3) 0%, rgba(111, 97, 241, 0.08) 50%, rgba(8, 145, 178, 0.15) 100%)',
        'gradient-cyan': 'linear-gradient(135deg, #0891b2 0%, #0e7490 100%)',
      },
      boxShadow: {
        'glow-cyan': '0 2px 12px rgba(8, 145, 178, 0.15)',
        'glow-purple': '0 2px 12px rgba(111, 97, 241, 0.15)',
        'glow-success': '0 2px 12px rgba(22, 163, 74, 0.15)',
        'glow-danger': '0 2px 12px rgba(220, 38, 38, 0.15)',
        'card': '0 1px 3px rgba(0, 0, 0, 0.08), 0 1px 2px rgba(0, 0, 0, 0.06)',
        'card-hover': '0 4px 12px rgba(0, 0, 0, 0.1)',
      },
      borderRadius: {
        'xl': '12px',
        '2xl': '16px',
        '3xl': '20px',
      },
      fontSize: {
        'xxs': '10px',
        'label': '11px',
      },
      spacing: {
        '18': '4.5rem',
        '22': '5.5rem',
      },
      animation: {
        'fade-in': 'fadeIn 0.3s ease-out',
        'slide-up': 'slideUp 0.4s ease-out',
        'slide-in-right': 'slideInRight 0.3s ease-out',
        'pulse-glow': 'pulseGlow 2s ease-in-out infinite',
        'spin-slow': 'spin 2s linear infinite',
      },
      keyframes: {
        fadeIn: {
          'from': { opacity: '0' },
          'to': { opacity: '1' },
        },
        slideUp: {
          'from': { opacity: '0', transform: 'translateY(10px)' },
          'to': { opacity: '1', transform: 'translateY(0)' },
        },
        slideInRight: {
          'from': { opacity: '0', transform: 'translateX(100%)' },
          'to': { opacity: '1', transform: 'translateX(0)' },
        },
        pulseGlow: {
          '0%, 100%': { boxShadow: '0 2px 12px rgba(8, 145, 178, 0.15)' },
          '50%': { boxShadow: '0 4px 20px rgba(8, 145, 178, 0.25)' },
        },
      },
    },
  },
  plugins: [],
}

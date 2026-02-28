/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        bg:      '#0B0F14',
        surface: '#111827',
        card:    '#0F172A',
        border:  '#1F2937',
        text:    '#E5E7EB',
        muted:   '#6B7280',
        violet:  '#8B5CF6',
        cyan:    '#22D3EE',
      },
    },
  },
  plugins: [],
}

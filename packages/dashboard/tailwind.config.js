/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  darkMode: "class",
  theme: {
    extend: {
      colors: {
        terminal: {
          bg: "#0a0e17",
          card: "#111827",
          border: "#1f2937",
          green: "#00e676",
          red: "#ff1744",
          amber: "#ffab00",
          blue: "#2979ff",
          purple: "#7c4dff",
          cyan: "#00e5ff",
          muted: "#6b7280",
        },
      },
      fontFamily: {
        mono: ['"JetBrains Mono"', '"Fira Code"', "monospace"],
      },
      animation: {
        pulse_slow: "pulse 3s cubic-bezier(0.4, 0, 0.6, 1) infinite",
      },
    },
  },
  plugins: [],
};

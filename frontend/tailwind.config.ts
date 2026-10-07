import type { Config } from "tailwindcss";

const config: Config = {
  content: [
    "./app/**/*.{ts,tsx}",
    "./components/**/*.{ts,tsx}",
    "./lib/**/*.{ts,tsx}"
  ],
  theme: {
    extend: {
      colors: {
        background: "#0B0D10",
        surface: "#111419",
        elevated: "#171B22",
        line: "#242A33",
        cyan: "#38BDF8",
        lime: "#84CC16",
        amber: "#F59E0B",
        coral: "#F87171"
      },
      fontFamily: {
        display: ["var(--font-display)", "Inter", "sans-serif"],
        body: ["var(--font-body)", "Inter", "sans-serif"]
      },
      boxShadow: {
        panel: "0 12px 40px rgba(0, 0, 0, 0.28)"
      }
    }
  },
  plugins: []
};

export default config;

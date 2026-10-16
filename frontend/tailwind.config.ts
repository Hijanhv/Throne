import type { Config } from "tailwindcss";

const config: Config = {
  content: ["./app/**/*.{ts,tsx}", "./components/**/*.{ts,tsx}", "./lib/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        bg: "#0a0a0a",
        surface: "#111111",
        raised: "#161616",
        line: "#1f1f1f",
        accent: "#00ff88",
        danger: "#ff4444",
        warn: "#ff9f1a",
        fg: "#ffffff",
        muted: "#888888",
      },
      fontFamily: {
        sans: ["var(--font-inter)", "ui-sans-serif", "system-ui", "sans-serif"],
        mono: ["var(--font-mono)", "ui-monospace", "SFMono-Regular", "monospace"],
      },
      keyframes: {
        blink: { "0%, 100%": { opacity: "1" }, "50%": { opacity: "0.25" } },
        dot: { "0%, 80%, 100%": { opacity: "0.2" }, "40%": { opacity: "1" } },
      },
      animation: {
        blink: "blink 1.2s ease-in-out infinite",
        dot: "dot 1.2s ease-in-out infinite",
      },
    },
  },
  plugins: [],
};

export default config;

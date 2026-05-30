import type { Config } from "tailwindcss";

const config: Config = {
  content: [
    "./src/**/*.{ts,tsx}",
    "../../packages/shared/**/*.{ts,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        // Quiet research palette — restrained, dense, dashboard-friendly.
        bg: {
          DEFAULT: "#0b0d10",
          panel: "#11151a",
          subtle: "#161b22",
        },
        ink: {
          DEFAULT: "#e6edf3",
          muted: "#8b949e",
          dim: "#6e7681",
        },
        accent: {
          DEFAULT: "#4f8bf0",
          up: "#22c55e",
          down: "#ef4444",
        },
        border: {
          DEFAULT: "#21262d",
        },
      },
      fontFamily: {
        sans: ["ui-sans-serif", "system-ui", "-apple-system", "Segoe UI", "Roboto", "sans-serif"],
        mono: ["ui-monospace", "SFMono-Regular", "Menlo", "monospace"],
      },
    },
  },
  plugins: [],
};

export default config;

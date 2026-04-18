import defaultTheme from "tailwindcss/defaultTheme";

/** @type {import('tailwindcss').Config} */
export default {
  darkMode: ["class"],
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
    "./node_modules/streamdown/dist/**/*.js",
    "./node_modules/@streamdown/*/dist/**/*.js",
  ],
  theme: {
    extend: {
      fontFamily: {
        sans: ["InterVariable", "Inter", ...defaultTheme.fontFamily.sans],
        mono: ["Geist Mono", ...defaultTheme.fontFamily.mono],
      },
      fontSize: {
        xs: ["0.8125rem", { lineHeight: "1.125rem" }], // 13px
        sm: ["0.875rem", { lineHeight: "1.25rem" }], // 14px
        base: ["1rem", { lineHeight: "1.5rem" }], // 16px
      },
      transitionTimingFunction: {
        "out-strong": "cubic-bezier(0.23, 1, 0.32, 1)",
      },
      animation: {
        "spin-slow": "spin 3s linear infinite",
      },
      boxShadow: {
        float: "0 4px 16px rgba(0, 0, 0, 0.08)",
        "float-lg": "0 8px 30px rgba(0, 0, 0, 0.08)",
        toast: "0 8px 24px -16px rgba(15, 15, 15, 0.35)",
        overlay: "0 24px 80px rgba(0, 0, 0, 0.14)",
      },
      borderRadius: {
        lg: "var(--radius)",
        md: "calc(var(--radius) - 2px)",
        sm: "calc(var(--radius) - 4px)",
      },
      colors: {
        background: "hsl(var(--background) / <alpha-value>)",
        foreground: "hsl(var(--foreground) / <alpha-value>)",
        surface: "hsl(var(--surface) / <alpha-value>)",
        card: {
          DEFAULT: "hsl(var(--card) / <alpha-value>)",
          foreground: "hsl(var(--card-foreground) / <alpha-value>)",
        },
        popover: {
          DEFAULT: "hsl(var(--popover) / <alpha-value>)",
          foreground: "hsl(var(--popover-foreground) / <alpha-value>)",
        },
        primary: {
          DEFAULT: "hsl(var(--primary) / <alpha-value>)",
          foreground: "hsl(var(--primary-foreground) / <alpha-value>)",
        },
        secondary: {
          DEFAULT: "hsl(var(--secondary) / <alpha-value>)",
          foreground: "hsl(var(--secondary-foreground) / <alpha-value>)",
        },
        muted: {
          DEFAULT: "hsl(var(--muted) / <alpha-value>)",
          foreground: "hsl(var(--muted-foreground) / <alpha-value>)",
        },
        accent: {
          DEFAULT: "hsl(var(--accent) / <alpha-value>)",
          foreground: "hsl(var(--accent-foreground) / <alpha-value>)",
        },
        destructive: {
          DEFAULT: "hsl(var(--destructive) / <alpha-value>)",
          foreground: "hsl(var(--destructive-foreground) / <alpha-value>)",
        },
        sidebar: {
          DEFAULT: "hsl(var(--sidebar) / <alpha-value>)",
          foreground: "hsl(var(--sidebar-foreground) / <alpha-value>)",
          border: "hsl(var(--sidebar-border) / <alpha-value>)",
        },
        "user-bubble": {
          DEFAULT: "rgb(229, 243, 255)",
          hover: "rgb(219, 238, 255)",
          text: "rgb(0, 40, 77)",
        },
        compaction: {
          label: "#5b6f92",
          text: "#2f3f5f",
        },
        rewind: {
          label: "#92725b",
          text: "#5f3f2f",
        },
        border: "hsl(var(--border) / <alpha-value>)",
        input: "hsl(var(--input) / <alpha-value>)",
        ring: "hsl(var(--ring) / <alpha-value>)",
        chart: {
          1: "hsl(var(--chart-1))",
          2: "hsl(var(--chart-2))",
          3: "hsl(var(--chart-3))",
          4: "hsl(var(--chart-4))",
          5: "hsl(var(--chart-5))",
        },
      },
    },
  },
  plugins: [require("tailwindcss-animate")],
};

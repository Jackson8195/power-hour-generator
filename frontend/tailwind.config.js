/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{js,ts,jsx,tsx}"],
  theme: {
    extend: {
      colors: {
        phosphor: {
          DEFAULT: "#1affe4",
          text: "#91fff2",
          bright: "#defffb",
        },
        magenta: {
          DEFAULT: "#ff2b9d",
          soft: "#ff77c2",
          text: "#ffb6dd",
          pale: "#ffd7eb",
        },
        crt: {
          bg: "#070b10",
          panel: "#08131a",
          deep: "#050a0f",
          pink: "#140913",
        },
      },
      fontFamily: {
        sans: ['"DM Sans"', "system-ui", "sans-serif"],
        mono: ['"Space Mono"', "monospace"],
        retro: ['"VT323"', '"Space Mono"', "monospace"],
        marker: ['"Permanent Marker"', "cursive"],
      },
      borderRadius: {
        bezel: "4px",
      },
      keyframes: {
        "crt-flicker": {
          "0%, 100%": { opacity: "1" },
          "92%": { opacity: "1" },
          "93%": { opacity: "0.82" },
          "94%": { opacity: "1" },
          "96%": { opacity: "0.88" },
          "97%": { opacity: "1" },
        },
        "disc-drop": {
          "0%": { transform: "translateY(-40px) scale(0.85)", opacity: "0" },
          "60%": { transform: "translateY(6px) scale(1.04)", opacity: "1" },
          "80%": { transform: "translateY(-3px) scale(0.98)", opacity: "1" },
          "100%": { transform: "translateY(0) scale(1)", opacity: "1" },
        },
        "disc-spin": {
          from: { transform: "rotate(0deg)" },
          to: { transform: "rotate(360deg)" },
        },
        "menu-slide": {
          from: { opacity: "0", transform: "translateX(-6px)" },
          to: { opacity: "1", transform: "translateX(0)" },
        },
      },
      animation: {
        "crt-flicker": "crt-flicker 8s ease-in-out infinite",
        "disc-drop": "disc-drop 0.5s cubic-bezier(0.22, 1, 0.36, 1) forwards",
        "disc-spin": "disc-spin 2s linear infinite",
        "menu-slide": "menu-slide 0.15s ease-out forwards",
      },
    },
  },
  plugins: [],
};

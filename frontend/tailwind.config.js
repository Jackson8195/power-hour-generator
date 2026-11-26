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
          light: "#ff9bd2",
        },
        status: {
          ok: "#7dffb0",
          warn: "#ffd166",
          error: "#ff8080",
        },
        crt: {
          bg: "#070b10",
          panel: "#08131a",
          deep: "#050a0f",
          pink: "#140913",
          wine: "#2b0b1d",
        },
      },
      fontFamily: {
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
        "menu-slide": {
          from: { opacity: "0", transform: "translateX(-6px)" },
          to: { opacity: "1", transform: "translateX(0)" },
        },
      },
      animation: {
        "crt-flicker": "crt-flicker 8s ease-in-out infinite",
        "menu-slide": "menu-slide 0.15s ease-out forwards",
      },
    },
  },
  plugins: [],
};

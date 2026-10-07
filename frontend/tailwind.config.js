/** @type {import('tailwindcss').Config} */
const color = (name) => `hsl(var(--${name}) / <alpha-value>)`;
export default {
  darkMode: "class", content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: { extend: {
    colors: Object.fromEntries(["surface", "link", "background", "foreground", "card", "card-foreground", "popover", "popover-foreground", "sidebar", "border", "input", "muted", "muted-foreground", "primary", "primary-hover", "primary-foreground", "secondary", "secondary-foreground", "accent", "accent-hover", "accent-foreground", "destructive", "success", "warning", "ring"].map((name) => [name, color(name)])),
    fontFamily: { sans: ["Inter", "system-ui", "-apple-system", "sans-serif"], serif: ["Newsreader", "Source Serif 4", "Georgia", "serif"] },
    borderRadius: { xl: "12px", lg: "8px" },
    boxShadow: { soft: "0 1px 2px hsl(var(--shadow) / 0.04)" },
    maxWidth: { "7xl": "1100px", "3xl": "768px" },
  } }, plugins: [],
};

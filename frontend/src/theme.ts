import { useEffect, useState } from "react";
export type Theme = "light" | "dark" | "system";
export function useTheme() {
  const [theme, setTheme] = useState<Theme>(() => {
    try { const stored = localStorage.getItem("research-theme"); return stored === "light" || stored === "dark" ? stored : "system"; }
    catch { return "system"; }
  });
  const [dark, setDark] = useState(() => document.documentElement.classList.contains("dark"));
  useEffect(() => {
    const media = window.matchMedia("(prefers-color-scheme: dark)");
    const apply = () => { const resolved = theme === "dark" || (theme === "system" && media.matches); document.documentElement.classList.toggle("dark", resolved); setDark(resolved); };
    apply();
    try { localStorage.setItem("research-theme", theme); } catch { /* Theme works when storage is unavailable. */ }
    media.addEventListener("change", apply);
    return () => media.removeEventListener("change", apply);
  }, [theme]);
  return { theme, setTheme, dark, cycleTheme: () => setTheme(theme === "system" ? "light" : theme === "light" ? "dark" : "system") };
}

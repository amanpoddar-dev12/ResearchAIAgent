import { Monitor, Moon, Sun } from "lucide-react";
import type { Theme } from "../theme";
const modes = [{ value: "light", label: "Light", Icon: Sun }, { value: "dark", label: "Dark", Icon: Moon }, { value: "system", label: "System", Icon: Monitor }] as const;
export function ThemeControl({ theme, onChange, compact = false }: { theme: Theme; onChange: (theme: Theme) => void; compact?: boolean }) {
 if (compact) { const current = modes.find(mode => mode.value === theme)!; const next = modes[(modes.indexOf(current) + 1) % modes.length]; const Icon = current.Icon;
  return <button type="button" className="theme-cycle icon-button" title={`Theme: ${current.label}. Switch to ${next.label}`} aria-label={`Theme: ${current.label}. Switch to ${next.label}`} onClick={() => onChange(next.value)}><Icon key={theme} size={18} className="theme-mode-icon" aria-hidden="true" /></button>;
 }
 return <div className="theme-options" role="group" aria-label="Color theme">{modes.map(({value,label,Icon}) => <button key={value} type="button" aria-pressed={theme === value} onClick={() => onChange(value)}><Icon size={16} aria-hidden="true" /><span>{label}</span></button>)}</div>;
}

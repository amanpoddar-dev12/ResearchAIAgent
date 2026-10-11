import { FindingsLogo } from "./FindingsLogo";
import { Menu, Moon, Sun, Plus } from "lucide-react";

export function Header({ dark, onTheme, onNew, onMenu, status, mode }: { dark: boolean; onTheme: () => void; onNew: () => void; onMenu: () => void; status: string; mode: string }) {
  return <header className="sticky top-0 z-10 border-b border-border/80 bg-background  dark:border-border dark:bg-background no-print">
    <div className="mx-auto flex max-w-7xl items-center justify-between gap-2 px-3 py-3 sm:px-6 sm:py-4 lg:px-8">
      <div className="flex min-w-0 items-center gap-2"><button className="icon-button" onClick={onMenu} aria-label="Open navigation"><Menu size={19} /></button><FindingsLogo tagline className="text-sm" /></div>
      <div className="flex shrink-0 items-center gap-1 sm:gap-2"><span className="badge hidden sm:inline-flex">{mode.replace("_", " ")} · {status}</span><button onClick={onNew} className="button-secondary min-h-10 px-2 sm:px-3" aria-label="Start new research"><Plus aria-hidden="true" size={16} /><span className="hidden sm:inline">New Research</span></button><button aria-label="Toggle theme" onClick={onTheme} className="icon-button min-h-10 min-w-10">{dark ? <Sun aria-hidden="true" size={18} /> : <Moon aria-hidden="true" size={18} />}</button></div>
    </div>
  </header>;
}

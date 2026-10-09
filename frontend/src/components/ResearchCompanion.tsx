import { useEffect, useState } from "react";

const phrases = ["Thinking", "Connecting the dots", "Cooking up insights", "Following the evidence", "Orchestrating ideas", "Reading between the lines", "Untangling the details", "Gathering clues"];

export type CompanionTask = "planning" | "search" | "evidence" | "finding" | "conflicts" | "synthesis";
const taskLabels: Record<CompanionTask, string> = { planning: "Thinking through your question", search: "Searching for sources", evidence: "Investigating the evidence", finding: "Finding connections", conflicts: "Checking conflicting claims", synthesis: "Writing your report" };

/** A decorative companion; actual research progress remains in the timeline. */
export function ResearchCompanion({ active = true, compact = false, task }: { active?: boolean; compact?: boolean; task?: CompanionTask }) {
  const [phrase, setPhrase] = useState(0);
  useEffect(() => {
    if (!active) return;
    const timer = window.setInterval(() => {
      setPhrase(current => (current + 1 + Math.floor(Math.random() * (phrases.length - 1))) % phrases.length);
    }, 4500);
    return () => window.clearInterval(timer);
  }, [active]);

  return <div className={compact ? "research-companion research-companion-compact mt-2 flex items-center justify-end gap-2" : "research-companion mt-4 rounded-xl border border-border bg-muted/40 px-3 py-2"} aria-label="Research companion" data-task={active ? task : undefined}>
    <div className="research-pet-playground" aria-hidden="true"><svg viewBox="0 0 64 64" className="research-pet h-14 w-14 shrink-0 text-primary" data-action={phrase % 3} aria-hidden="true">
      <ellipse cx="32" cy="57" rx="15" ry="2" className="fill-foreground/10" />
      <g className="research-pet-body">
        <path d="M18 24Q12 8 25 16Q32 12 39 16Q52 8 46 24Q54 49 40 53H24Q10 49 18 24Z" fill="currentColor" />
        <path className="research-pet-wing" d="M18 31Q6 26 10 39Q13 45 19 43" fill="currentColor" stroke="currentColor" strokeWidth="2" />
        <path d="M46 31Q58 26 54 39Q51 45 45 43" fill="currentColor" />
        <g className="research-pet-eyes fill-primary-foreground">
          <ellipse cx="25" cy="29" rx="5" ry="6" /><ellipse cx="39" cy="29" rx="5" ry="6" />
          <circle cx="26" cy="30" r="2" className="fill-foreground" /><circle cx="38" cy="30" r="2" className="fill-foreground" />
        </g>
        <path d="M29 36L32 40L35 36" className="fill-primary-foreground" />
        <path d="M21 44L32 47L43 44V53L32 56L21 53Z" className="fill-card stroke-border" strokeWidth="1.5" />
        <path d="M32 47V55M24 48L29 49M35 49L40 48" className="stroke-muted-foreground" fill="none" strokeWidth="1.5" />
      </g>
    </svg></div>
    <div className="min-w-0 text-center"><p className="text-sm font-medium text-foreground" aria-hidden="true">{active ? task ? taskLabels[task] : phrases[phrase] : "Ready when you are"}<span className="research-pet-dots">…</span></p>{!compact && <p className="text-xs text-muted-foreground">{active ? "Your research companion is on the case." : "Ask a question — let’s explore together."}</p>}</div>
  </div>;
}

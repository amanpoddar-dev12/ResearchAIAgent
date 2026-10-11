type FindingsLogoProps = {
  size?: number;
  tagline?: boolean;
  className?: string;
};

/** A discovery lens: a clear focus with a spark of insight. */
export function FindingsLogo({ size = 24, tagline = false, className = "" }: FindingsLogoProps) {
  return <span aria-label="FindingsAI" className={`inline-flex min-w-0 items-center gap-2 ${className}`}>
    <svg aria-hidden="true" focusable="false" width={size} height={size} viewBox="0 0 24 24" fill="none" className="shrink-0 text-link" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round">
      <circle cx="10.5" cy="10.5" r="7.5" />
      <path d="m16 16 5 5" />
      <path d="m10.5 6 .9 3.6 3.6.9-3.6.9-.9 3.6-.9-3.6-3.6-.9 3.6-.9Z" fill="currentColor" stroke="none" />
    </svg>
    <span className="min-w-0">
      <span className="block truncate font-sans font-medium tracking-tight text-foreground">Findings<span className="font-semibold text-link">AI</span></span>
      {tagline && <span className="hidden text-xs text-muted-foreground sm:block">Evidence, organized</span>}
    </span>
  </span>;
}

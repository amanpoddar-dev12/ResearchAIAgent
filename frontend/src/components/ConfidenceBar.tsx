export function ConfidenceBar({ value, label = "Confidence" }: { value?: number; label?: string }) {
  if (value === undefined || !Number.isFinite(value)) return <span className="text-xs text-muted-foreground">Not available</span>;
  const percent = Math.round(Math.max(0, Math.min(1, value)) * 100);
  return <div className="min-w-28" title={`${label} is a system-generated estimate, not a probability of truth.`}><div className="mb-1 flex justify-between text-xs"><span>{label}</span><span>{percent}%</span></div><div className="h-1.5 overflow-hidden rounded-full bg-muted dark:bg-surface" role="progressbar" aria-label={label} aria-valuenow={percent} aria-valuemin={0} aria-valuemax={100}><div className="h-full rounded-full bg-primary transition-colors motion-reduce:transition-none" style={{ width: `${percent}%` }} /></div></div>;
}

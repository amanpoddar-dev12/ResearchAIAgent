import { Info } from "lucide-react";

export function MetricCard({ label, value, description }: { label: string; value: string | number; description: string }) {
  return <article className="metric-card" title={description}>
    <div className="flex items-center justify-between gap-2"><p className="metric-label">{label}</p><Info size={14} aria-label={description} /></div>
    <p className="mt-2 text-2xl font-medium tracking-tight">{value}</p>
  </article>;
}

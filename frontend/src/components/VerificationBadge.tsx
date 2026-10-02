import { AlertTriangle, Check, HelpCircle, Minus } from "lucide-react";
import type { Finding } from "../types/research";

const config = {
  Supported: { icon: Check, className: "badge-success", label: "Supported" },
  "Partially Supported": { icon: Minus, className: "badge-indigo", label: "Partially supported" },
  Contradicted: { icon: AlertTriangle, className: "badge-error", label: "Contradicted" },
  Unverified: { icon: HelpCircle, className: "badge", label: "Unverified" },
} as const;

export function VerificationBadge({ status }: { status?: Finding["evidence_status"] }) {
  const item = config[status || "Unverified"];
  const Icon = item.icon;
  return <span className={`badge gap-1 ${item.className}`}><Icon size={13} aria-hidden="true" />{item.label}</span>;
}

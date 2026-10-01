import type { SourceQuality } from "../types/research";
import { ConfidenceBar } from "./ConfidenceBar";

export function QualityScore({ quality }: { quality?: SourceQuality }) {
  return <div title="System-generated research metric based on relevance, authority, freshness, source type, and evidence strength.">
    <ConfidenceBar value={quality?.total} label="Source quality" />
  </div>;
}

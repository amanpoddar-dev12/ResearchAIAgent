import type { ResearchMode, ResearchGap } from '../types/research';
export const modeHelp: Record<ResearchMode, string> = {
  quick: 'A concise answer with a short research budget. Complex questions may remain unresolved.',
  deep: 'Explore multiple perspectives, follow evidence gaps, and investigate disagreements.',
  technical: 'Focus on documentation, implementation details, versions, and constraints.',
  academic: 'Examine original studies, methods, limitations, and corroborating evidence.',
  fact_check: 'Seek supporting and contradicting evidence for specific claims.',
  compare: 'Compare named items against common criteria; missing evidence stays explicit.',
  standard: 'A balanced overview of available evidence.',
};
export function gapLabel(gap: ResearchGap): string {
  if (/no verified evidence|unverified/i.test(gap.description)) return 'Find supporting evidence';
  if (/independent|corroboration/i.test(gap.description)) return 'Find independent corroboration';
  if (/contradict|conflict/i.test(gap.description)) return 'Investigate a disagreement';
  if (/stages|budget|timeout/i.test(gap.description)) return 'Complete the unfinished analysis';
  return gap.description.replace(/^[A-Za-z]+\d+:\s*/, '');
}
export function usefulIdea(question: string): boolean {
  const topic = question.replace(/^What does the evidence say about\s+/i, '').replace(/\?$/, '');
  return topic.split(/\s+/).length >= 4 && !/^(Artificial Intelligence(?:\s*\|.*)?|Science|ScienceDaily(?::.*)?|Science \| AAAS)$/i.test(topic);
}

import type { History, LocalizedText, PublicData } from '../data/schema.ts';

export interface HistorySupplement {
  id: string;
  category: 'education' | 'experience';
  match: { organization: string; start: string };
  lab: { name: LocalizedText; url: string };
}

function matches(item: History, supplement: HistorySupplement): boolean {
  return item.start === supplement.match.start
    && Object.values(item.organization).includes(supplement.match.organization);
}

export function historySupplement(item: History, category: HistorySupplement['category'], entries: HistorySupplement[]) {
  return entries.find((entry) => entry.category === category && matches(item, entry));
}

export function currentLab(id: string | undefined, entries: HistorySupplement[], data: Pick<PublicData, 'education' | 'experience'>) {
  const entry = entries.find((item) => item.id === id);
  // A deleted or restricted researchmap record must also hide its manual supplement.
  return entry && data[entry.category].some((item) => matches(item, entry)) ? entry.lab : undefined;
}

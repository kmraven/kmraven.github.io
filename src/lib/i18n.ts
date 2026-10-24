import type { Locale, LocalizedText, LocalizedAuthors, Profile } from '../data/schema.ts';

export type PageKey = 'home' | 'cv';
export const pagePaths: Record<PageKey, string> = { home: '', cv: 'cv/' };
export function pagePath(page: PageKey, lang: Locale): string {
  return `${lang === 'en' ? '/en/' : '/'}${pagePaths[page]}`;
}
export function translated(value: LocalizedText | undefined, lang: Locale): { text: string; lang: Locale } {
  if (value?.[lang]) return { text: value[lang], lang };
  const other = lang === 'ja' ? 'en' : 'ja';
  return { text: value?.[other] ?? '', lang: other };
}
export function localize(value: LocalizedText | undefined, lang: Locale): string {
  return translated(value, lang).text;
}
export function authorNames(value: LocalizedAuthors, lang: Locale): { names: string[]; lang: Locale } {
  if (value[lang]) return { names: value[lang], lang };
  const other = lang === 'ja' ? 'en' : 'ja';
  return { names: value[other] ?? [], lang: other };
}
export function fullName(profile: Pick<Profile, 'givenName' | 'familyName'>, lang: Locale): string {
  const family = localize(profile.familyName, lang);
  const given = localize(profile.givenName, lang);
  if (lang === 'ja') return `${family}${given}`;
  const displayFamily = /^[A-Z -]+$/.test(family)
    ? family.toLowerCase().replace(/\b\w/g, (character) => character.toUpperCase()) : family;
  return `${given} ${displayFamily}`;
}
export function formatDate(value: string | undefined, lang: Locale): string {
  if (!value) return '';
  const [year, month, day] = value.split('-').map(Number);
  if (!month) return lang === 'ja' ? `${year}年` : String(year);
  if (lang === 'ja') return `${year}年${month}月${day ? `${day}日` : ''}`;
  return new Intl.DateTimeFormat('en-US', {
    year: 'numeric', month: 'short', ...(day ? { day: 'numeric' as const } : {}), timeZone: 'UTC',
  }).format(new Date(Date.UTC(year, month - 1, day ?? 1)));
}
export function formatPeriod(start: string | undefined, end: string | null | undefined, lang: Locale): string {
  const from = formatDate(start, lang);
  const to = end === null ? (lang === 'ja' ? '現在' : 'Present') : formatDate(end, lang);
  return [from, to].filter(Boolean).join(' – ');
}

export function hasResearchContent(published: boolean | undefined, body: string | undefined): boolean {
  return Boolean(published && body?.replace(/<!--[\s\S]*?-->/g, '').trim());
}

export function pageDescription(page: PageKey, lang: Locale, name: string): string {
  const detail = copy[lang][`${page}Description`];
  return lang === 'ja' ? `${name}の${detail}` : `${name}. ${detail}`;
}

export const copy = {
  ja: {
    home: 'ホーム', publications: '業績', cv: 'CV', skip: '本文へ移動', navigation: 'メインナビゲーション',
    profile: '研究者プロフィール', externalProfiles: '外部プロフィール', links: 'リンク',
    researchAreas: '研究分野', latest: '最近の論文・プレプリント', viewAll: 'すべての業績',
    publicationsTitle: '研究業績', publicationsSubtitle: '論文・プレプリントと学会発表の一覧。',
    papers: '論文', preprints: 'プレプリント', presentations: '学会発表',
    cvTitle: 'Curriculum Vitae', cvSubtitle: '所属・経歴・学歴・研究業績。',
    affiliation: '所属', experience: '経歴', education: '学歴', print: 'CVを印刷',
    abstract: '概要を読む', poster: 'ポスター発表', oral: '口頭発表', other: '発表',
    moreProfile: 'プロフィール・研究活動', cvLink: '経歴・学歴を見る',
    homeDescription: '研究者プロフィール。所属、研究分野、論文・プレプリント、学会発表、CVを掲載しています。',
    publicationsDescription: '研究業績。論文・プレプリント、学会発表と関連資料へのリンク。',
    cvDescription: 'Web CV。公開している所属、経歴、学歴、研究分野と研究業績。',
    printNote: '印刷用のレイアウトに対応しています。',
  },
  en: {
    home: 'Home', publications: 'Publications', cv: 'CV', skip: 'Skip to content', navigation: 'Main navigation',
    profile: 'Research profile', externalProfiles: 'Elsewhere', links: 'Links',
    researchAreas: 'Research areas', latest: 'Recent papers & preprints', viewAll: 'All publications',
    publicationsTitle: 'Publications', publicationsSubtitle: 'Papers, preprints, and conference presentations.',
    papers: 'Papers', preprints: 'Preprints', presentations: 'Conference presentations',
    cvTitle: 'Curriculum Vitae', cvSubtitle: 'Affiliation, experience, education, and research outputs.',
    affiliation: 'Affiliation', experience: 'Experience', education: 'Education', print: 'Print CV',
    abstract: 'Read abstract', poster: 'Poster presentation', oral: 'Oral presentation', other: 'Presentation',
    moreProfile: 'Profile & research', cvLink: 'View experience & education',
    homeDescription: 'Research profile, affiliation, research areas, papers, preprints, conference presentations, and curriculum vitae.',
    publicationsDescription: 'Papers, preprints, and conference presentations, with links to related resources.',
    cvDescription: 'Academic curriculum vitae: affiliation, experience, education, research areas, and research outputs.',
    printNote: 'A print layout is available.',
  },
} as const;

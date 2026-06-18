export type Lang = 'en' | 'zh';

export function getLang(url: URL): Lang {
  const match = url.pathname.match(/^\/(en|zh)(\/|$)/);
  if (match) return match[1] as Lang;
  return 'en';
}

export function localizePath(path: string, lang: Lang): string {
  const clean = path.replace(/^\/(en|zh)(\/|$)/, '/');
  const normalized = clean.startsWith('/') ? clean : `/${clean}`;
  const suffix = normalized === '/' ? '' : normalized;
  return `/${lang}${suffix}`;
}

export function alternateLang(lang: Lang): Lang {
  return lang === 'en' ? 'zh' : 'en';
}

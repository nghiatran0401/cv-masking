export const MAX_SOURCE_URLS = 50;
export const MAX_SOURCE_URL_LENGTH = 2048;

export type SourceLink = {
  href: string;
  label: string;
};

export function parseSourceLinks(text: string): SourceLink[] {
  const seen = new Set<string>();
  const links: SourceLink[] = [];
  for (const raw of text.split(/[\s,;]+/)) {
    if (raw === "") {
      continue;
    }
    const href = allowedHref(raw);
    if (href === null || seen.has(href)) {
      continue;
    }
    seen.add(href);
    links.push({ href, label: linkLabel(href) });
    if (links.length >= MAX_SOURCE_URLS) {
      break;
    }
  }
  return links;
}

function allowedHref(raw: string): string | null {
  if (raw.length > MAX_SOURCE_URL_LENGTH) {
    return null;
  }
  let parsed: URL;
  try {
    parsed = new URL(raw);
  } catch {
    return null;
  }
  if (parsed.protocol !== "https:" && parsed.protocol !== "http:") {
    return null;
  }
  if (parsed.username !== "" || parsed.password !== "") {
    return null;
  }
  if (parsed.hostname === "") {
    return null;
  }
  return parsed.href;
}

function linkLabel(href: string): string {
  let parsed: URL;
  try {
    parsed = new URL(href);
  } catch {
    return "link";
  }
  const parts = parsed.pathname.split("/").filter((part) => part.length > 0);
  const last = parts[parts.length - 1];
  if (last === undefined) {
    return parsed.hostname;
  }
  try {
    return decodeURIComponent(last);
  } catch {
    return last;
  }
}

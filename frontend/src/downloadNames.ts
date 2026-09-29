export const ALL_MASKED_ZIP_NAME = "output.zip";
export const OUTPUT_ROOT = "output";

const UNSAFE_ASCII = new Set(["<", ">", ":", '"', "/", "\\", "|", "?", "*"]);
const KNOWN_EXT = /\.(pdf|docx)$/i;

export type CandidateArchiveLayout = {
  originalPath: string;
  maskedPath: string;
};

export function maskedDownloadName(
  originalName: string | undefined,
  format: "pdf" | "docx" | null,
  documentId: string,
): string {
  const ext = extensionFor(format, originalName);
  const stem = stemFrom(originalName, documentId);
  return `masked_${stem}${ext}`;
}

export function originalDownloadName(
  originalName: string | undefined,
  format: "pdf" | "docx" | null,
  documentId: string,
): string {
  const ext = extensionFor(format, originalName);
  const stem = stemFrom(originalName, documentId);
  return `${stem}${ext}`;
}

export function uniqueDownloadName(name: string, used: Set<string>): string {
  const key = name.toLowerCase();
  if (!used.has(key)) {
    used.add(key);
    return name;
  }
  const split = splitExt(name);
  let n = 2;
  let candidate = `${split.stem}-${String(n)}${split.ext}`;
  while (used.has(candidate.toLowerCase())) {
    n += 1;
    candidate = `${split.stem}-${String(n)}${split.ext}`;
  }
  used.add(candidate.toLowerCase());
  return candidate;
}

export function uniqueFolderName(name: string, used: Set<string>): string {
  const key = name.toLowerCase();
  if (!used.has(key)) {
    used.add(key);
    return name;
  }
  let n = 2;
  let candidate = `${name} ${String(n)}`;
  while (used.has(candidate.toLowerCase())) {
    n += 1;
    candidate = `${name} ${String(n)}`;
  }
  used.add(candidate.toLowerCase());
  return candidate;
}

export function candidateArchiveLayout(
  originalName: string | undefined,
  format: "pdf" | "docx" | null,
  documentId: string,
  usedFolders: Set<string>,
): CandidateArchiveLayout {
  const folder = uniqueFolderName(
    `candidate ${stemFrom(originalName, documentId)}`,
    usedFolders,
  );
  const dir = `${OUTPUT_ROOT}/${folder}`;
  return {
    originalPath: `${dir}/${originalDownloadName(originalName, format, documentId)}`,
    maskedPath: `${dir}/${maskedDownloadName(originalName, format, documentId)}`,
  };
}

export function isCvFile(file: File): boolean {
  const name = basename(file.name);
  if (name.startsWith(".") || name.startsWith("~$")) {
    return false;
  }
  return KNOWN_EXT.test(name);
}

export function cvFilesFrom(list: readonly File[]): File[] {
  return list.filter((file) => isCvFile(file));
}

function extensionFor(
  format: "pdf" | "docx" | null,
  originalName: string | undefined,
): string {
  switch (format) {
    case "pdf":
      return ".pdf";
    case "docx":
      return ".docx";
    case null:
      return extensionFromName(originalName);
    default: {
      const exhaustive: never = format;
      return exhaustive;
    }
  }
}

function extensionFromName(originalName: string | undefined): string {
  if (originalName === undefined) {
    return "";
  }
  const match = KNOWN_EXT.exec(basename(originalName));
  if (match === null || match[1] === undefined) {
    return "";
  }
  return `.${match[1].toLowerCase()}`;
}

function stemFrom(
  originalName: string | undefined,
  documentId: string,
): string {
  const fallback = shortId(documentId);
  if (originalName === undefined) {
    return fallback;
  }
  const sanitized = sanitizeStem(stripKnownExt(basename(originalName)));
  return sanitized.length === 0 ? fallback : sanitized;
}

function basename(name: string): string {
  const parts = name.replace(/\\/g, "/").split("/");
  return parts[parts.length - 1] ?? name;
}

function stripKnownExt(name: string): string {
  return name.replace(KNOWN_EXT, "");
}

function sanitizeStem(stem: string): string {
  let cleaned = "";
  for (const ch of stem) {
    const code = ch.codePointAt(0) ?? 0;
    cleaned += code < 32 || UNSAFE_ASCII.has(ch) ? "_" : ch;
  }
  return cleaned
    .replace(/^\.+/g, "")
    .replace(/[. ]+$/g, "")
    .trim()
    .slice(0, 180);
}

function shortId(documentId: string): string {
  const hex = documentId.replace(/[^0-9a-f]/gi, "");
  const sliced = hex.slice(0, 8);
  return sliced.length === 0 ? "cv" : sliced;
}

function splitExt(name: string): { stem: string; ext: string } {
  const match = /^(.*)(\.[^.]+)$/.exec(name);
  if (match === null || match[1] === undefined || match[2] === undefined) {
    return { stem: name, ext: "" };
  }
  return { stem: match[1], ext: match[2] };
}

import { MAX_SOURCE_URL_LENGTH, MAX_SOURCE_URLS } from "./urlList";

/** Keep aligned with SOURCE_CV_HOST in the backend domain. Hostname only, no scheme. */
export const SOURCE_CV_HOST = "data.ehiring.ehr.vib";

export const MAX_CV_DOWNLOAD_BYTES = 20 * 1024 * 1024;

const PDF_MAGIC = [0x25, 0x50, 0x44, 0x46] as const;
const ZIP_MAGIC = [0x50, 0x4b, 0x03, 0x04] as const;
const CV_EXTENSION = /\.(pdf|docx)$/i;
const UNSAFE_NAME_CHARS = new Set([
  "<",
  ">",
  ":",
  '"',
  "|",
  "?",
  "*",
  "\\",
  "/",
]);

export type CvDownloadFailure =
  "host" | "http" | "redirect" | "not_cv" | "too_large" | "network";

export type CvDownloadResult = { ok: true; file: File } | RejectedUrl;

export type CvFolder = {
  exists(name: string): Promise<boolean>;
  write(name: string, data: Uint8Array): Promise<void>;
};

type CvWritable = {
  write(data: Blob): Promise<void>;
  close(): Promise<void>;
};

type CvFileHandle = {
  createWritable(): Promise<CvWritable>;
};

export type CvDirectoryHandle = {
  getFileHandle(
    name: string,
    options?: { create?: boolean },
  ): Promise<CvFileHandle>;
};

type DownloadDeps = {
  folder: CvFolder;
  reservedNames: Set<string>;
  fetchImpl?: typeof fetch;
  maxBytes?: number;
};

type AcceptedUrl = {
  ok: true;
  href: string;
  fileName: string;
};

type RejectedUrl = {
  ok: false;
  label: string;
  reason: CvDownloadFailure;
};

type UrlGate = AcceptedUrl | RejectedUrl;

export function isDownloadableCvUrl(href: string): boolean {
  return acceptCvUrl(href).ok;
}

export function fitsInBatch(occupied: number, incoming: number): boolean {
  if (!Number.isSafeInteger(occupied) || !Number.isSafeInteger(incoming)) {
    return false;
  }
  if (occupied < 0 || incoming < 0) {
    return false;
  }
  return occupied + incoming <= MAX_SOURCE_URLS;
}

export function canPickCvFolder(target: Window = window): boolean {
  return readDirectoryPicker(target) !== null;
}

export async function pickCvFolder(
  target: Window = window,
): Promise<CvDirectoryHandle | "cancelled" | "unavailable"> {
  const picker = readDirectoryPicker(target);
  if (picker === null) {
    return "unavailable";
  }
  try {
    return await picker();
  } catch (error: unknown) {
    if (error instanceof DOMException && error.name === "AbortError") {
      return "cancelled";
    }
    throw error;
  }
}

export function folderFromDirectory(directory: CvDirectoryHandle): CvFolder {
  return {
    async exists(name: string): Promise<boolean> {
      try {
        await directory.getFileHandle(name);
        return true;
      } catch (error: unknown) {
        if (error instanceof DOMException && error.name === "NotFoundError") {
          return false;
        }
        throw error;
      }
    },
    async write(name: string, data: Uint8Array): Promise<void> {
      const handle = await directory.getFileHandle(name, { create: true });
      const writable = await handle.createWritable();
      const copy = new Uint8Array(data.byteLength);
      copy.set(data);
      await writable.write(new Blob([copy]));
      await writable.close();
    },
  };
}

export async function downloadCvFile(
  href: string,
  deps: DownloadDeps,
): Promise<CvDownloadResult> {
  const accepted = acceptCvUrl(href);
  if (!accepted.ok) {
    return accepted;
  }
  const maxBytes = deps.maxBytes ?? MAX_CV_DOWNLOAD_BYTES;
  const fetchImpl = deps.fetchImpl ?? fetch;
  try {
    const response = await fetchImpl(accepted.href, {
      method: "GET",
      credentials: "include",
      cache: "no-store",
      redirect: "follow",
      referrerPolicy: "no-referrer",
    });
    return await storeResponse(response, accepted, deps, maxBytes);
  } catch {
    return failed(accepted.fileName, "network");
  }
}

function acceptCvUrl(href: string): UrlGate {
  if (href.length > MAX_SOURCE_URL_LENGTH) {
    return failed("link", "host");
  }
  let parsed: URL;
  try {
    parsed = new URL(href);
  } catch {
    return failed("link", "host");
  }
  const fileName = safeCvFileName(parsed);
  const label = fileName ?? pathLabel(parsed);
  if (parsed.username !== "" || parsed.password !== "") {
    return failed(label, "host");
  }
  if (parsed.protocol === "http:") {
    return failed(label, parsed.hostname === SOURCE_CV_HOST ? "http" : "host");
  }
  if (parsed.protocol !== "https:" || parsed.hostname !== SOURCE_CV_HOST) {
    return failed(label, "host");
  }
  if (parsed.port !== "" && parsed.port !== "443") {
    return failed(label, "host");
  }
  if (fileName === null) {
    return failed(label, "not_cv");
  }
  return { ok: true, href: parsed.href, fileName };
}

async function storeResponse(
  response: Response,
  accepted: AcceptedUrl,
  deps: DownloadDeps,
  maxBytes: number,
): Promise<CvDownloadResult> {
  if (response.type === "opaque" || response.type === "opaqueredirect") {
    return failed(accepted.fileName, "network");
  }
  const finalUrl = finalHttpsUrl(response.url);
  if (finalUrl === null || finalUrl.hostname !== SOURCE_CV_HOST) {
    await discard(response);
    return failed(accepted.fileName, "redirect");
  }
  if (!response.ok) {
    await discard(response);
    return failed(accepted.fileName, "network");
  }
  const contentType = (
    response.headers.get("content-type") ?? ""
  ).toLowerCase();
  if (
    contentType.includes("text/html") ||
    contentType.includes("application/xhtml")
  ) {
    await discard(response);
    return failed(accepted.fileName, "not_cv");
  }
  if (declaredTooLarge(response.headers.get("content-length"), maxBytes)) {
    await discard(response);
    return failed(accepted.fileName, "too_large");
  }
  const bytes = await readLimited(response, maxBytes);
  if (bytes === "too_large") {
    return failed(accepted.fileName, "too_large");
  }
  if (!matchesCv(accepted.fileName, bytes)) {
    return failed(accepted.fileName, "not_cv");
  }
  const name = await allocateName(
    accepted.fileName,
    deps.folder,
    deps.reservedNames,
  );
  await deps.folder.write(name, bytes);
  return { ok: true, file: fileFromBytes(name, bytes) };
}

function finalHttpsUrl(value: string): URL | null {
  try {
    const parsed = new URL(value);
    if (
      parsed.protocol !== "https:" ||
      parsed.username !== "" ||
      parsed.password !== ""
    ) {
      return null;
    }
    return parsed;
  } catch {
    return null;
  }
}

function declaredTooLarge(header: string | null, maxBytes: number): boolean {
  if (header === null) {
    return false;
  }
  if (!/^\d+$/.test(header)) {
    return true;
  }
  const size = Number(header);
  return !Number.isSafeInteger(size) || size > maxBytes;
}

async function readLimited(
  response: Response,
  maxBytes: number,
): Promise<Uint8Array | "too_large"> {
  if (response.body === null) {
    const buffer = new Uint8Array(await response.arrayBuffer());
    if (buffer.byteLength > maxBytes) {
      return "too_large";
    }
    return buffer;
  }
  const reader = response.body.getReader();
  const chunks: Uint8Array[] = [];
  let total = 0;
  for (;;) {
    const step = await reader.read();
    if (step.done) {
      break;
    }
    total += step.value.byteLength;
    if (total > maxBytes) {
      await reader.cancel();
      return "too_large";
    }
    chunks.push(step.value);
  }
  const out = new Uint8Array(total);
  let offset = 0;
  for (const chunk of chunks) {
    out.set(chunk, offset);
    offset += chunk.byteLength;
  }
  return out;
}

async function discard(response: Response): Promise<void> {
  try {
    await response.body?.cancel();
  } catch {
    // The body is already closed.
  }
}

function matchesCv(fileName: string, bytes: Uint8Array): boolean {
  if (fileName.endsWith(".pdf")) {
    return startsWith(bytes, PDF_MAGIC);
  }
  if (fileName.endsWith(".docx")) {
    return startsWith(bytes, ZIP_MAGIC);
  }
  return false;
}

function startsWith(bytes: Uint8Array, prefix: readonly number[]): boolean {
  if (bytes.byteLength < prefix.length) {
    return false;
  }
  for (let index = 0; index < prefix.length; index += 1) {
    if (bytes[index] !== prefix[index]) {
      return false;
    }
  }
  return true;
}

async function allocateName(
  preferred: string,
  folder: CvFolder,
  reservedNames: Set<string>,
): Promise<string> {
  let candidate = preferred;
  let index = 1;
  while (
    reservedNames.has(candidate.toLowerCase()) ||
    (await folder.exists(candidate))
  ) {
    index += 1;
    if (index > 1000) {
      throw new Error("cv-name");
    }
    candidate = suffixedCvName(preferred, index);
  }
  reservedNames.add(candidate.toLowerCase());
  return candidate;
}

function suffixedCvName(preferred: string, index: number): string {
  const match = CV_EXTENSION.exec(preferred);
  if (match === null) {
    return `${preferred} (${String(index)})`;
  }
  const extension = match[0].toLowerCase();
  const stem = preferred.slice(0, -extension.length);
  return `${stem} (${String(index)})${extension}`;
}

function safeCvFileName(parsed: URL): string | null {
  const parts = parsed.pathname.split("/").filter((part) => part.length > 0);
  const last = parts[parts.length - 1];
  if (last === undefined) {
    return null;
  }
  let decoded: string;
  try {
    decoded = decodeURIComponent(last);
  } catch {
    return null;
  }
  if (decoded.length === 0 || decoded.length > 200) {
    return null;
  }
  if (decoded.startsWith(".") || decoded.includes("..")) {
    return null;
  }
  if (hasUnsafeNameChar(decoded)) {
    return null;
  }
  const match = CV_EXTENSION.exec(decoded);
  if (match === null || match[1] === undefined) {
    return null;
  }
  return `${decoded.slice(0, -match[0].length)}.${match[1].toLowerCase()}`;
}

function pathLabel(parsed: URL): string {
  const parts = parsed.pathname.split("/").filter((part) => part.length > 0);
  const last = parts[parts.length - 1];
  if (
    last === undefined ||
    last.includes("/") ||
    last.includes(":") ||
    last.length > 200
  ) {
    return "link";
  }
  try {
    const decoded = decodeURIComponent(last);
    if (
      decoded.includes("/") ||
      decoded.includes("\\") ||
      decoded.includes(":")
    ) {
      return "link";
    }
    return decoded;
  } catch {
    return "link";
  }
}

function hasUnsafeNameChar(name: string): boolean {
  for (const char of name) {
    const code = char.codePointAt(0) ?? 0;
    if (code <= 31 || UNSAFE_NAME_CHARS.has(char)) {
      return true;
    }
  }
  return false;
}

function failed(label: string, reason: CvDownloadFailure): RejectedUrl {
  return { ok: false, label, reason };
}

function fileFromBytes(name: string, bytes: Uint8Array): File {
  const copy = new Uint8Array(bytes.byteLength);
  copy.set(bytes);
  const type = name.endsWith(".docx")
    ? "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    : "application/pdf";
  return new File([copy], name, { type });
}

function readDirectoryPicker(
  target: Window,
): (() => Promise<CvDirectoryHandle>) | null {
  const value: unknown = Reflect.get(target, "showDirectoryPicker");
  if (typeof value !== "function") {
    return null;
  }
  const picker = value as (this: Window) => Promise<CvDirectoryHandle>;
  return () => picker.call(target);
}

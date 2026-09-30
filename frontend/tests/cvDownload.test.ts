import { describe, expect, it, vi } from "vitest";

import {
  MAX_CV_DOWNLOAD_BYTES,
  SOURCE_CV_HOST,
  canPickCvFolder,
  downloadCvFile,
  fitsInBatch,
  folderFromDirectory,
  isDownloadableCvUrl,
  pickCvFolder,
  type CvDirectoryHandle,
  type CvFolder,
} from "../src/cvDownload";
import { MAX_SOURCE_URLS } from "../src/urlList";

const PDF = new Uint8Array([0x25, 0x50, 0x44, 0x46, 0x2d, 0x31, 0x2e, 0x34]);
const DOCX = new Uint8Array([0x50, 0x4b, 0x03, 0x04, 0x14, 0x00]);
const HTML = new TextEncoder().encode(
  "<!DOCTYPE html><title>synthetic</title>",
);

const PDF_HREF = `https://${SOURCE_CV_HOST}/2026/synthetic-cv.pdf`;
const DOCX_HREF = `https://${SOURCE_CV_HOST}/2026/synthetic-cv.docx`;

function requestHref(input: RequestInfo | URL): string {
  if (typeof input === "string") {
    return input;
  }
  if (input instanceof URL) {
    return input.href;
  }
  return input.url;
}

function memoryFolder(existing: readonly string[] = []): CvFolder & {
  written: Map<string, Uint8Array>;
} {
  const written = new Map<string, Uint8Array>();
  const names = new Set(existing);
  return {
    written,
    exists(name: string): Promise<boolean> {
      return Promise.resolve(names.has(name) || written.has(name));
    },
    write(name: string, data: Uint8Array): Promise<void> {
      names.add(name);
      written.set(name, data);
      return Promise.resolve();
    },
  };
}

function cvResponse(
  finalUrl: string,
  bytes: Uint8Array,
  headers: Record<string, string> = {},
  status = 200,
): Response {
  const copy = Uint8Array.from(bytes);
  const response = new Response(copy, { status, headers });
  Object.defineProperty(response, "url", { value: finalUrl });
  return response;
}

describe("downloadCvFile", () => {
  it("saves an allowlisted PDF and DOCX without calling any other host", async () => {
    const folder = memoryFolder();
    const reserved = new Set<string>();
    const fetchImpl = vi.fn((input: RequestInfo | URL) => {
      const href = requestHref(input);
      const bytes = href.endsWith(".docx") ? DOCX : PDF;
      const type = href.endsWith(".docx")
        ? "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        : "application/pdf";
      return Promise.resolve(cvResponse(href, bytes, { "content-type": type }));
    });

    const pdf = await downloadCvFile(PDF_HREF, {
      folder,
      reservedNames: reserved,
      fetchImpl,
    });
    const docx = await downloadCvFile(DOCX_HREF, {
      folder,
      reservedNames: reserved,
      fetchImpl,
    });

    expect(pdf.ok).toBe(true);
    expect(docx.ok).toBe(true);
    if (pdf.ok && docx.ok) {
      expect(pdf.file.name).toBe("synthetic-cv.pdf");
      expect(docx.file.name).toBe("synthetic-cv.docx");
      expect(new Uint8Array(await pdf.file.arrayBuffer())).toEqual(PDF);
    }
    expect(folder.written.has("synthetic-cv.pdf")).toBe(true);
    expect(folder.written.has("synthetic-cv.docx")).toBe(true);
    expect(fetchImpl).toHaveBeenCalledWith(
      PDF_HREF,
      expect.objectContaining({
        credentials: "include",
        cache: "no-store",
        redirect: "follow",
        referrerPolicy: "no-referrer",
      }),
    );
    expect(SOURCE_CV_HOST.includes("://")).toBe(false);
    expect(MAX_CV_DOWNLOAD_BYTES).toBe(20 * 1024 * 1024);
  });

  it("does not overwrite a file already in the folder", async () => {
    const folder = memoryFolder(["synthetic-cv.pdf"]);
    const fetchImpl = vi.fn(() =>
      Promise.resolve(
        cvResponse(PDF_HREF, PDF, { "content-type": "application/pdf" }),
      ),
    );
    const result = await downloadCvFile(PDF_HREF, {
      folder,
      reservedNames: new Set(),
      fetchImpl,
    });
    expect(result.ok).toBe(true);
    if (result.ok) {
      expect(result.file.name).toBe("synthetic-cv (2).pdf");
    }
    expect(folder.written.has("synthetic-cv.pdf")).toBe(false);
    expect(folder.written.has("synthetic-cv (2).pdf")).toBe(true);
  });

  it("rejects the wrong host, http, an off-host redirect, HTML, oversize, and network errors", async () => {
    const folder = memoryFolder();
    const fetchImpl = vi.fn();

    const wrongHost = await downloadCvFile(
      "https://intranet.example.invalid/synthetic-cv.pdf",
      { folder, reservedNames: new Set(), fetchImpl },
    );
    const httpLink = await downloadCvFile(
      `http://${SOURCE_CV_HOST}/synthetic-cv.pdf`,
      {
        folder,
        reservedNames: new Set(),
        fetchImpl,
      },
    );
    expect(wrongHost).toEqual({
      ok: false,
      label: "synthetic-cv.pdf",
      reason: "host",
    });
    expect(httpLink).toEqual({
      ok: false,
      label: "synthetic-cv.pdf",
      reason: "http",
    });
    expect(fetchImpl).not.toHaveBeenCalled();
    expect(isDownloadableCvUrl(PDF_HREF)).toBe(true);
    expect(
      isDownloadableCvUrl(`http://${SOURCE_CV_HOST}/synthetic-cv.pdf`),
    ).toBe(false);

    fetchImpl.mockResolvedValueOnce(
      cvResponse("https://intranet.example.invalid/other.pdf", PDF),
    );
    const redirected = await downloadCvFile(PDF_HREF, {
      folder,
      reservedNames: new Set(),
      fetchImpl,
    });
    expect(redirected).toEqual({
      ok: false,
      label: "synthetic-cv.pdf",
      reason: "redirect",
    });

    fetchImpl.mockResolvedValueOnce(
      cvResponse(PDF_HREF, HTML, {
        "content-type": "text/html; charset=utf-8",
      }),
    );
    const htmlType = await downloadCvFile(PDF_HREF, {
      folder,
      reservedNames: new Set(),
      fetchImpl,
    });
    expect(htmlType).toEqual({
      ok: false,
      label: "synthetic-cv.pdf",
      reason: "not_cv",
    });

    fetchImpl.mockResolvedValueOnce(
      cvResponse(PDF_HREF, HTML, {
        "content-type": "application/octet-stream",
      }),
    );
    const htmlBody = await downloadCvFile(PDF_HREF, {
      folder,
      reservedNames: new Set(),
      fetchImpl,
    });
    expect(htmlBody).toEqual({
      ok: false,
      label: "synthetic-cv.pdf",
      reason: "not_cv",
    });

    fetchImpl.mockResolvedValueOnce(
      cvResponse(PDF_HREF, PDF, {
        "content-length": String(MAX_CV_DOWNLOAD_BYTES + 1),
      }),
    );
    const declared = await downloadCvFile(PDF_HREF, {
      folder,
      reservedNames: new Set(),
      fetchImpl,
    });
    expect(declared).toEqual({
      ok: false,
      label: "synthetic-cv.pdf",
      reason: "too_large",
    });

    const oversized = new Uint8Array(9);
    oversized.set(PDF);
    fetchImpl.mockResolvedValueOnce(cvResponse(PDF_HREF, oversized));
    const streamed = await downloadCvFile(PDF_HREF, {
      folder,
      reservedNames: new Set(),
      fetchImpl,
      maxBytes: PDF.byteLength,
    });
    expect(streamed).toEqual({
      ok: false,
      label: "synthetic-cv.pdf",
      reason: "too_large",
    });

    fetchImpl.mockRejectedValueOnce(new TypeError("Failed to fetch"));
    const network = await downloadCvFile(PDF_HREF, {
      folder,
      reservedNames: new Set(),
      fetchImpl,
    });
    expect(network).toEqual({
      ok: false,
      label: "synthetic-cv.pdf",
      reason: "network",
    });
    expect(JSON.stringify(network).includes("Failed to fetch")).toBe(false);
    expect(folder.written.size).toBe(0);
  });

  it("keeps a same-host redirect and the original file name", async () => {
    const folder = memoryFolder();
    const fetchImpl = vi.fn(() =>
      Promise.resolve(
        cvResponse(`https://${SOURCE_CV_HOST}/other/renamed.pdf`, PDF, {
          "content-type": "application/pdf",
        }),
      ),
    );
    const result = await downloadCvFile(PDF_HREF, {
      folder,
      reservedNames: new Set(),
      fetchImpl,
    });
    expect(result.ok).toBe(true);
    if (result.ok) {
      expect(result.file.name).toBe("synthetic-cv.pdf");
    }
  });
});

describe("batch capacity and folder picker", () => {
  it("refuses a batch that cannot hold every link", () => {
    expect(fitsInBatch(0, MAX_SOURCE_URLS)).toBe(true);
    expect(fitsInBatch(1, MAX_SOURCE_URLS)).toBe(false);
    expect(fitsInBatch(49, 1)).toBe(true);
    expect(fitsInBatch(49, 2)).toBe(false);
  });

  it("treats a cancelled picker as a stop and writes through the directory handle", async () => {
    const target = {
      showDirectoryPicker: vi.fn(() =>
        Promise.reject(new DOMException("aborted", "AbortError")),
      ),
    } as unknown as Window;
    expect(canPickCvFolder(target)).toBe(true);
    await expect(pickCvFolder(target)).resolves.toBe("cancelled");

    const names = new Set<string>(["synthetic-cv.pdf"]);
    const written: string[] = [];
    const directory: CvDirectoryHandle = {
      getFileHandle(name: string, options?: { create?: boolean }) {
        if (!names.has(name) && options?.create !== true) {
          return Promise.reject(new DOMException("missing", "NotFoundError"));
        }
        names.add(name);
        return Promise.resolve({
          createWritable() {
            return Promise.resolve({
              write() {
                written.push(name);
                return Promise.resolve();
              },
              close() {
                return Promise.resolve();
              },
            });
          },
        });
      },
    };
    const folder = folderFromDirectory(directory);
    expect(await folder.exists("synthetic-cv.pdf")).toBe(true);
    expect(await folder.exists("other.pdf")).toBe(false);
    await folder.write("other.pdf", PDF);
    expect(written).toEqual(["other.pdf"]);
  });
});

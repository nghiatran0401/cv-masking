import {
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { App } from "../src/App";
import { SOURCE_CV_HOST } from "../src/cvDownload";
import { MESSAGES, messageForCode, messageForState } from "../src/i18n";
import type { DocumentView } from "../src/types";

const ALLOWED_CV = `https://${SOURCE_CV_HOST}/2026/synthetic-cv.pdf`;

const viCopy = MESSAGES;

beforeEach(() => {
  sessionStorage.clear();
  vi.stubGlobal(
    "fetch",
    vi.fn((input: RequestInfo | URL) => {
      const url = requestUrl(input);
      if (url.includes("/api/session")) {
        return json({ csrf_token: "test-csrf" });
      }
      throw new Error(`unexpected ${url}`);
    }),
  );
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("App", () => {
  it("defaults to Vietnamese and states the app is local-only", () => {
    render(<App />);
    expect(
      screen.getByRole("heading", { level: 1, name: viCopy.title }),
    ).toBeInTheDocument();
    expect(screen.getByText(viCopy.localOnly)).toBeInTheDocument();
    expect(
      screen.getByText(`${viCopy.maskedNotice} ${viCopy.photoNotice}`),
    ).toBeInTheDocument();
    expect(document.documentElement.lang).toBe("vi");
    expect(
      screen.queryByRole("button", { name: "English" }),
    ).not.toBeInTheDocument();
  });

  it("exposes salary as the only optional policy control", () => {
    render(<App />);
    const boxes = screen.getAllByRole("checkbox");
    expect(boxes).toHaveLength(1);
    expect(boxes[0]).toBeChecked();
    expect(screen.getByText(viCopy.salaryHelp)).toBeInTheDocument();
  });

  it("offers a folder picker and ignores a folder with no CV files", async () => {
    render(<App />);
    expect(screen.getByText(viCopy.browseFolder)).toBeInTheDocument();
    expect(screen.getByText(viCopy.urlHelp)).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText(viCopy.browseFolder), {
      target: {
        files: [new File(["synthetic"], ".DS_Store")],
      },
    });
    expect(await screen.findByText(viCopy.noCvInFolder)).toBeInTheDocument();
  });

  it("turns pasted http(s) URLs into browser links and ignores javascript", () => {
    render(<App />);
    fireEvent.change(screen.getByLabelText(viCopy.urlPaste), {
      target: {
        value:
          "https://intranet.example.invalid/path/synthetic-cv.pdf\njavascript:alert(1)",
      },
    });
    const link = screen.getByRole("link", { name: "synthetic-cv.pdf" });
    expect(link).toHaveAttribute(
      "href",
      "https://intranet.example.invalid/path/synthetic-cv.pdf",
    );
    expect(link).toHaveAttribute("rel", "noopener noreferrer");
    expect(link).toHaveAttribute("target", "_blank");
    expect(
      screen.queryByRole("link", { name: /alert/i }),
    ).not.toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: viCopy.downloadLinks }),
    ).toBeDisabled();
  });

  it("asks the local server to fetch an allowlisted link and enables start", async () => {
    const batchId = "00000000-0000-4000-8000-0000000000aa";
    const documentId = "00000000-0000-4000-8000-0000000000d1";
    let imported = false;
    const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const url = requestUrl(input);
      if (url.includes("/api/session")) {
        return json({ csrf_token: "test-csrf" });
      }
      if (url === "/api/batches" && init?.method === "POST") {
        return json({
          batch_id: batchId,
          state: "open",
          mask_salary: true,
          document_count: 0,
          version: 0,
        });
      }
      if (url.endsWith(`/documents/${documentId}/input`)) {
        return new Response("%PDF-synthetic-original\n", {
          status: 200,
          headers: { "Content-Type": "application/pdf" },
        });
      }
      if (url.endsWith("/source-links") && init?.method === "POST") {
        if (typeof init.body !== "string") {
          throw new Error("expected a JSON body");
        }
        expect(JSON.parse(init.body)).toEqual({ url: ALLOWED_CV });
        expect(url.startsWith("https://")).toBe(false);
        imported = true;
        return json({
          document_id: documentId,
          batch_id: batchId,
          state: "uploaded",
          document_format: "pdf",
          size_bytes: 12,
          attempt: 0,
          error_code: null,
          review_reasons: [],
          can_approve: false,
          has_output: false,
          finding_counts: null,
          residual_counts: {},
          residual_pages: {},
          hidden_removed: {},
          version: 1,
        });
      }
      if (url.endsWith(`/api/batches/${batchId}`)) {
        return json({
          batch_id: batchId,
          state: "open",
          mask_salary: true,
          document_count: imported ? 1 : 0,
          version: imported ? 1 : 0,
          documents: imported
            ? [
                {
                  document_id: documentId,
                  batch_id: batchId,
                  state: "uploaded",
                  document_format: "pdf",
                  size_bytes: 12,
                  attempt: 0,
                  error_code: null,
                  review_reasons: [],
                  can_approve: false,
                  has_output: false,
                  finding_counts: null,
                  residual_counts: {},
                  residual_pages: {},
                  hidden_removed: {},
                  version: 1,
                },
              ]
            : [],
        });
      }
      throw new Error(`unexpected ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    render(<App />);
    const button = screen.getByRole("button", { name: viCopy.downloadLinks });
    expect(button).toBeDisabled();
    fireEvent.change(screen.getByLabelText(viCopy.urlPaste), {
      target: { value: "https://intranet.example.invalid/synthetic-cv.pdf" },
    });
    expect(button).toBeDisabled();
    fireEvent.change(screen.getByLabelText(viCopy.urlPaste), {
      target: { value: ALLOWED_CV },
    });
    expect(button).toBeEnabled();
    fireEvent.click(button);
    expect(
      await screen.findByText(messageForState("uploaded")),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: viCopy.start })).toBeEnabled();
    const urls = fetchMock.mock.calls.map((call) => requestUrl(call[0]));
    expect(urls.some((url) => url.startsWith("https://"))).toBe(false);
    expect(urls.some((url) => url.endsWith("/source-links"))).toBe(true);
    expect(urls.some((url) => url.endsWith("/input"))).toBe(true);
  });

  it("puts the linked CV and its masked file in a folder named for the file", async () => {
    const batchId = "00000000-0000-4000-8000-0000000000aa";
    const documentId = "00000000-0000-4000-8000-0000000000d1";
    let imported = false;
    const downloads = captureDownloads();
    const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const url = requestUrl(input);
      if (url.includes("/api/session")) {
        return json({ csrf_token: "test-csrf" });
      }
      if (url === "/api/batches" && init?.method === "POST") {
        return json({
          batch_id: batchId,
          state: "open",
          mask_salary: true,
          document_count: 0,
          version: 0,
        });
      }
      if (url.endsWith(`/documents/${documentId}/input`)) {
        return new Response("%PDF-synthetic-original\n", {
          status: 200,
          headers: { "Content-Type": "application/pdf" },
        });
      }
      if (url.endsWith(`/documents/${documentId}/download`)) {
        return pdfDownload(documentId);
      }
      if (url.endsWith("/source-links") && init?.method === "POST") {
        imported = true;
        return json(
          documentView({
            document_id: documentId,
            batch_id: batchId,
            state: "uploaded",
            version: 1,
          }),
        );
      }
      if (url.endsWith(`/api/batches/${batchId}`)) {
        return json({
          batch_id: batchId,
          state: imported ? "finished" : "open",
          mask_salary: true,
          document_count: imported ? 1 : 0,
          version: imported ? 2 : 0,
          documents: imported
            ? [
                documentView({
                  document_id: documentId,
                  batch_id: batchId,
                  state: "completed",
                  has_output: true,
                  version: 2,
                }),
              ]
            : [],
        });
      }
      throw new Error(`unexpected ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    render(<App />);
    fireEvent.change(screen.getByLabelText(viCopy.urlPaste), {
      target: { value: ALLOWED_CV },
    });
    fireEvent.click(screen.getByRole("button", { name: viCopy.downloadLinks }));
    await waitFor(() => {
      expect(
        screen.getByRole("button", { name: viCopy.downloadAll }),
      ).toBeInTheDocument();
    });
    fireEvent.click(screen.getByRole("button", { name: viCopy.downloadAll }));
    try {
      await waitFor(() => {
        expect(downloads.names).toEqual(["output.zip"]);
      });
      const zip = downloads.blobs[0];
      if (zip === undefined) {
        throw new Error("expected a zip blob");
      }
      const bytes = new Uint8Array(await zip.arrayBuffer());
      expect(zipEntryNames(bytes)).toEqual([
        "output/synthetic-cv/synthetic-cv.pdf",
        "output/synthetic-cv/masked_synthetic-cv.pdf",
      ]);
      fireEvent.click(
        screen.getByRole("button", { name: viCopy.downloadMasked }),
      );
      await waitFor(() => {
        expect(downloads.names).toEqual(["output.zip", "masked.zip"]);
      });
      const maskedZip = downloads.blobs[1];
      if (maskedZip === undefined) {
        throw new Error("expected a masked zip blob");
      }
      const maskedBytes = new Uint8Array(await maskedZip.arrayBuffer());
      expect(zipEntryNames(maskedBytes)).toEqual([
        "masked/masked_synthetic-cv.pdf",
      ]);
    } finally {
      downloads.restore();
    }
  });

  it("shows a failed link by the name already on screen", async () => {
    const batchId = "00000000-0000-4000-8000-0000000000aa";
    vi.stubGlobal(
      "fetch",
      vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
        const url = requestUrl(input);
        if (url.includes("/api/session")) {
          return json({ csrf_token: "test-csrf" });
        }
        if (url === "/api/batches" && init?.method === "POST") {
          return json({
            batch_id: batchId,
            state: "open",
            mask_salary: true,
            document_count: 0,
            version: 0,
          });
        }
        if (url.endsWith("/source-links")) {
          return jsonStatus(400, { code: "UPLOAD_SOURCE_UNAVAILABLE" });
        }
        if (url.endsWith(`/api/batches/${batchId}`)) {
          return json({
            batch_id: batchId,
            state: "open",
            mask_salary: true,
            document_count: 0,
            version: 0,
            documents: [],
          });
        }
        throw new Error(`unexpected ${url}`);
      }),
    );
    render(<App />);
    fireEvent.change(screen.getByLabelText(viCopy.urlPaste), {
      target: { value: ALLOWED_CV },
    });
    fireEvent.click(screen.getByRole("button", { name: viCopy.downloadLinks }));
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "synthetic-cv.pdf",
    );
    expect(screen.getByRole("alert")).toHaveTextContent(
      messageForCode("UPLOAD_SOURCE_UNAVAILABLE"),
    );
    expect(screen.getByRole("button", { name: viCopy.start })).toBeDisabled();
  });

  it("keeps file names in the table after a mocked upload", async () => {
    const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const url = requestUrl(input);
      if (url.includes("/api/session")) {
        return json({ csrf_token: "test-csrf" });
      }
      if (url === "/api/batches" && init?.method === "POST") {
        return json({
          batch_id: "00000000-0000-4000-8000-0000000000aa",
          state: "open",
          mask_salary: true,
          document_count: 0,
          version: 0,
        });
      }
      if (
        url.endsWith("/api/batches/00000000-0000-4000-8000-0000000000aa") &&
        init?.method !== "POST" &&
        init?.method !== "PATCH" &&
        init?.method !== "DELETE"
      ) {
        return json({
          batch_id: "00000000-0000-4000-8000-0000000000aa",
          state: "open",
          mask_salary: true,
          document_count: 1,
          version: 1,
          documents: [
            {
              document_id: "00000000-0000-4000-8000-0000000000d1",
              batch_id: "00000000-0000-4000-8000-0000000000aa",
              state: "uploaded",
              document_format: "pdf",
              size_bytes: 12,
              attempt: 0,
              error_code: null,
              review_reasons: [],
              can_approve: false,
              has_output: false,
              finding_counts: null,
              residual_counts: {},
              residual_pages: {},
              hidden_removed: {},
              version: 1,
            },
          ],
        });
      }
      throw new Error(`unexpected ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    const xhr = mockXhr({
      document_id: "00000000-0000-4000-8000-0000000000d1",
      batch_id: "00000000-0000-4000-8000-0000000000aa",
      state: "uploaded",
      document_format: "pdf",
      size_bytes: 12,
      attempt: 0,
      error_code: null,
      review_reasons: [],
      can_approve: false,
      has_output: false,
      finding_counts: null,
      residual_counts: {},
      residual_pages: {},
      hidden_removed: {},
      version: 1,
    });
    vi.stubGlobal("XMLHttpRequest", xhr.ctor);
    render(<App />);
    const input = document.querySelector('input[type="file"]');
    expect(input).toBeInstanceOf(HTMLInputElement);
    fireEvent.change(input as HTMLInputElement, {
      target: {
        files: [
          new File(["%PDF-synthetic\n"], "synthetic-mau.pdf", {
            type: "application/pdf",
          }),
        ],
      },
    });
    await waitFor(() => {
      expect(screen.getByText("synthetic-mau.pdf")).toBeInTheDocument();
    });
    expect(screen.getByText(messageForState("uploaded"))).toBeInTheDocument();
    expect(fetchMock).not.toHaveBeenCalledWith(
      expect.stringMatching(/^https?:\/\/(?!127\.0\.0\.1)/),
    );
    expect(screen.queryByText("%PDF-synthetic")).not.toBeInTheDocument();
  });

  it("retries a failed document in a started batch without creating a new one", async () => {
    const batchId = "00000000-0000-4000-8000-0000000000aa";
    const failedId = "00000000-0000-4000-8000-0000000000d2";
    const retriedId = "00000000-0000-4000-8000-0000000000d3";
    const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const url = requestUrl(input);
      if (url.includes("/api/session")) {
        return json({ csrf_token: "test-csrf" });
      }
      if (url === "/api/batches" && init?.method === "POST") {
        return json({
          batch_id: batchId,
          state: "open",
          mask_salary: true,
          document_count: 0,
          version: 0,
        });
      }
      if (
        url.endsWith(`/api/batches/${batchId}`) &&
        init?.method !== "POST" &&
        init?.method !== "PATCH" &&
        init?.method !== "DELETE"
      ) {
        return json({
          batch_id: batchId,
          state: "finished",
          mask_salary: true,
          document_count: 1,
          version: 4,
          documents: [
            documentView({
              document_id: failedId,
              batch_id: batchId,
              state: "failed",
              error_code: "REDACT_SANITIZE_FAILED",
              version: 3,
            }),
          ],
        });
      }
      throw new Error(`unexpected ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    const xhr = mockXhr(
      documentView({
        document_id: failedId,
        batch_id: batchId,
        state: "uploaded",
        version: 1,
      }),
    );
    vi.stubGlobal("XMLHttpRequest", xhr.ctor);
    render(<App />);
    const input = document.querySelector('input[type="file"]');
    fireEvent.change(input as HTMLInputElement, {
      target: {
        files: [
          new File(["%PDF-synthetic\n"], "synthetic-ok.pdf", {
            type: "application/pdf",
          }),
        ],
      },
    });
    await waitFor(() => {
      expect(
        screen.getByRole("button", { name: viCopy.retry }),
      ).toBeInTheDocument();
    });
    xhr.opened.length = 0;
    xhr.setResponse(
      documentView({
        document_id: retriedId,
        batch_id: batchId,
        state: "uploaded",
        version: 1,
      }),
    );
    fireEvent.click(screen.getByRole("button", { name: viCopy.retry }));
    await waitFor(() => {
      expect(xhr.opened).toContain(
        `/api/batches/${batchId}/documents?replaces=${failedId}`,
      );
    });
    expect(screen.queryByText(viCopy.retryMissing)).not.toBeInTheDocument();
  });

  it("shows a failed document beside a completed one and offers only the masked ZIP", async () => {
    const batchId = "00000000-0000-4000-8000-0000000000aa";
    const doneId = "00000000-0000-4000-8000-0000000000d1";
    const failedId = "00000000-0000-4000-8000-0000000000d2";
    const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const url = requestUrl(input);
      if (url.includes("/api/session")) {
        return json({ csrf_token: "test-csrf" });
      }
      if (url === "/api/batches" && init?.method === "POST") {
        return json({
          batch_id: batchId,
          state: "open",
          mask_salary: true,
          document_count: 0,
          version: 0,
        });
      }
      if (
        url.endsWith(`/api/batches/${batchId}`) &&
        init?.method !== "POST" &&
        init?.method !== "PATCH" &&
        init?.method !== "DELETE"
      ) {
        return json({
          batch_id: batchId,
          state: "finished",
          mask_salary: true,
          document_count: 2,
          version: 4,
          documents: [
            documentView({
              document_id: doneId,
              batch_id: batchId,
              state: "completed",
              has_output: true,
              finding_counts: { email: 1 },
              version: 4,
            }),
            documentView({
              document_id: failedId,
              batch_id: batchId,
              state: "failed",
              error_code: "VERIFY_RESIDUAL_DETECTION",
              has_output: true,
              residual_counts: { email: 1 },
              residual_pages: { email: [1] },
              version: 3,
            }),
          ],
        });
      }
      throw new Error(`unexpected ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    const xhr = mockXhr(
      documentView({
        document_id: doneId,
        batch_id: batchId,
        state: "uploaded",
        version: 1,
      }),
    );
    vi.stubGlobal("XMLHttpRequest", xhr.ctor);
    render(<App />);
    const input = document.querySelector('input[type="file"]');
    fireEvent.change(input as HTMLInputElement, {
      target: {
        files: [
          new File(["%PDF-synthetic\n"], "synthetic-ok.pdf", {
            type: "application/pdf",
          }),
        ],
      },
    });
    await waitFor(() => {
      expect(screen.getByText(viCopy.downloadAll)).toBeInTheDocument();
    });
    expect(screen.getByText(messageForState("completed"))).toBeInTheDocument();
    expect(screen.getByText(messageForState("failed"))).toBeInTheDocument();
    expect(
      screen.getByText(messageForCode("VERIFY_RESIDUAL_DETECTION")),
    ).toBeInTheDocument();
    expect(screen.getByText(/Còn sót, không chia sẻ:/)).toBeInTheDocument();
    expect(
      screen.getAllByRole("button", { name: viCopy.download }),
    ).toHaveLength(2);
    expect(screen.getAllByRole("button", { name: viCopy.view })).toHaveLength(
      2,
    );
    expect(
      screen.getByRole("button", { name: viCopy.downloadAll }),
    ).toBeInTheDocument();
    expect(screen.queryByText("%PDF-synthetic")).not.toBeInTheDocument();
  });

  it("does not offer a PDF preview for a completed Word file", async () => {
    const batchId = "00000000-0000-4000-8000-0000000000aa";
    const doneId = "00000000-0000-4000-8000-0000000000d1";
    const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const url = requestUrl(input);
      if (url.includes("/api/session")) {
        return json({ csrf_token: "test-csrf" });
      }
      if (url === "/api/batches" && init?.method === "POST") {
        return json({
          batch_id: batchId,
          state: "open",
          mask_salary: true,
          document_count: 0,
          version: 0,
        });
      }
      if (
        url.endsWith(`/api/batches/${batchId}`) &&
        init?.method !== "POST" &&
        init?.method !== "PATCH" &&
        init?.method !== "DELETE"
      ) {
        return json({
          batch_id: batchId,
          state: "finished",
          mask_salary: true,
          document_count: 1,
          version: 4,
          documents: [
            documentView({
              document_id: doneId,
              batch_id: batchId,
              state: "completed",
              document_format: "docx",
              has_output: true,
              version: 4,
            }),
          ],
        });
      }
      throw new Error(`unexpected ${url}`);
    });
    renderAfterUpload(
      fetchMock,
      "synthetic-ok.docx",
      "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    );
    await waitFor(() => {
      expect(screen.getByText(viCopy.downloadAll)).toBeInTheDocument();
    });
    expect(
      screen.getByRole("button", { name: viCopy.download }),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: viCopy.view }),
    ).not.toBeInTheDocument();
  });

  it("saves a completed file as masked_ plus the original file name", async () => {
    const batchId = "00000000-0000-4000-8000-0000000000aa";
    const doneId = "00000000-0000-4000-8000-0000000000d1";
    const downloads = captureDownloads();
    const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const url = requestUrl(input);
      if (url.includes("/api/session")) {
        return json({ csrf_token: "test-csrf" });
      }
      if (url === "/api/batches" && init?.method === "POST") {
        return json({
          batch_id: batchId,
          state: "open",
          mask_salary: true,
          document_count: 0,
          version: 0,
        });
      }
      if (
        url.endsWith(`/api/batches/${batchId}/documents/${doneId}/download`)
      ) {
        return pdfDownload(doneId);
      }
      if (
        url.endsWith(`/api/batches/${batchId}`) &&
        init?.method !== "POST" &&
        init?.method !== "PATCH" &&
        init?.method !== "DELETE"
      ) {
        return json({
          batch_id: batchId,
          state: "finished",
          mask_salary: true,
          document_count: 1,
          version: 4,
          documents: [
            documentView({
              document_id: doneId,
              batch_id: batchId,
              state: "completed",
              has_output: true,
              version: 4,
            }),
          ],
        });
      }
      throw new Error(`unexpected ${url}`);
    });
    renderAfterUpload(fetchMock, "synthetic-cv.pdf");
    await waitFor(() => {
      expect(
        screen.getByRole("button", { name: viCopy.download }),
      ).toBeInTheDocument();
    });
    fireEvent.click(screen.getByRole("button", { name: viCopy.download }));
    try {
      await waitFor(() => {
        expect(downloads.names).toEqual(["masked_synthetic-cv.pdf"]);
      });
    } finally {
      downloads.restore();
    }
  });

  it("zips review-required files and skips sanitize failures", async () => {
    const batchId = "00000000-0000-4000-8000-0000000000aa";
    const doneId = "00000000-0000-4000-8000-0000000000d1";
    const failedId = "00000000-0000-4000-8000-0000000000d2";
    const downloads = captureDownloads();
    const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const url = requestUrl(input);
      if (url.includes("/api/session")) {
        return json({ csrf_token: "test-csrf" });
      }
      if (url === "/api/batches" && init?.method === "POST") {
        return json({
          batch_id: batchId,
          state: "open",
          mask_salary: true,
          document_count: 0,
          version: 0,
        });
      }
      if (
        url.endsWith(`/api/batches/${batchId}/documents/${doneId}/download`)
      ) {
        return pdfDownload(doneId);
      }
      if (
        url.endsWith(`/api/batches/${batchId}`) &&
        init?.method !== "POST" &&
        init?.method !== "PATCH" &&
        init?.method !== "DELETE"
      ) {
        return json({
          batch_id: batchId,
          state: "finished",
          mask_salary: true,
          document_count: 2,
          version: 4,
          documents: [
            documentView({
              document_id: doneId,
              batch_id: batchId,
              state: "review_required",
              has_output: true,
              review_reasons: ["DETECT_LOW_CONFIDENCE"],
              finding_counts: { email: 1 },
              version: 4,
            }),
            documentView({
              document_id: failedId,
              batch_id: batchId,
              state: "failed",
              error_code: "REDACT_SANITIZE_FAILED",
              has_output: false,
              version: 3,
            }),
          ],
        });
      }
      throw new Error(`unexpected ${url}`);
    });
    renderAfterUpload(fetchMock, "synthetic-cv.pdf");
    await waitFor(() => {
      expect(
        screen.getByRole("button", { name: viCopy.downloadAll }),
      ).toBeInTheDocument();
    });
    fireEvent.click(screen.getByRole("button", { name: viCopy.downloadAll }));
    try {
      await waitFor(() => {
        expect(downloads.names).toEqual(["output.zip"]);
      });
      const zip = downloads.blobs[0];
      if (zip === undefined) {
        throw new Error("expected a zip blob");
      }
      const bytes = new Uint8Array(await zip.arrayBuffer());
      expect(zipEntryNames(bytes)).toEqual([
        "output/synthetic-cv/synthetic-cv.pdf",
        "output/synthetic-cv/masked_synthetic-cv.pdf",
      ]);
      const requested = fetchMock.mock.calls.map(([input]) =>
        requestUrl(input),
      );
      expect(
        requested.some(
          (url) => url.includes(failedId) && url.endsWith("/download"),
        ),
      ).toBe(false);
    } finally {
      downloads.restore();
    }
  });

  it("opens a completed PDF in a dialog from the download endpoint and revokes the blob on close", async () => {
    const batchId = "00000000-0000-4000-8000-0000000000aa";
    const doneId = "00000000-0000-4000-8000-0000000000d1";
    const objectUrl = "blob:http://127.0.0.1/synthetic-preview";
    const createObjectURL = vi
      .spyOn(URL, "createObjectURL")
      .mockReturnValue(objectUrl);
    const revokeObjectURL = vi
      .spyOn(URL, "revokeObjectURL")
      .mockImplementation(() => undefined);
    const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const url = requestUrl(input);
      if (url.includes("/api/session")) {
        return json({ csrf_token: "test-csrf" });
      }
      if (url === "/api/batches" && init?.method === "POST") {
        return json({
          batch_id: batchId,
          state: "open",
          mask_salary: true,
          document_count: 0,
          version: 0,
        });
      }
      if (
        url.endsWith(`/api/batches/${batchId}`) &&
        init?.method !== "POST" &&
        init?.method !== "PATCH" &&
        init?.method !== "DELETE"
      ) {
        return json({
          batch_id: batchId,
          state: "finished",
          mask_salary: true,
          document_count: 1,
          version: 4,
          documents: [
            documentView({
              document_id: doneId,
              batch_id: batchId,
              state: "completed",
              has_output: true,
              version: 4,
            }),
          ],
        });
      }
      if (url === `/api/batches/${batchId}/documents/${doneId}/download`) {
        return pdfDownload(doneId);
      }
      throw new Error(`unexpected ${url}`);
    });
    renderAfterUpload(fetchMock);
    await waitFor(() => {
      expect(
        screen.getByRole("button", { name: viCopy.view }),
      ).toBeInTheDocument();
    });
    fireEvent.click(screen.getByRole("button", { name: viCopy.view }));
    await waitFor(() => {
      expect(screen.getByRole("dialog")).toBeInTheDocument();
    });
    expect(screen.getByTitle(viCopy.preview)).toHaveAttribute("src", objectUrl);
    expect(createObjectURL).toHaveBeenCalledTimes(1);
    fireEvent.click(screen.getByRole("button", { name: viCopy.closePreview }));
    await waitFor(() => {
      expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    });
    expect(revokeObjectURL).toHaveBeenCalledWith(objectUrl);
    createObjectURL.mockRestore();
    revokeObjectURL.mockRestore();
  });

  it("lets HR keep or deny a review PDF from the preview dialog", async () => {
    const batchId = "00000000-0000-4000-8000-0000000000aa";
    const reviewId = "00000000-0000-4000-8000-0000000000d1";
    const objectUrl = "blob:http://127.0.0.1/synthetic-review";
    const createObjectURL = vi
      .spyOn(URL, "createObjectURL")
      .mockReturnValue(objectUrl);
    const revokeObjectURL = vi
      .spyOn(URL, "revokeObjectURL")
      .mockImplementation(() => undefined);
    const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const url = requestUrl(input);
      if (url.includes("/api/session")) {
        return json({ csrf_token: "test-csrf" });
      }
      if (url === "/api/batches" && init?.method === "POST") {
        return json({
          batch_id: batchId,
          state: "open",
          mask_salary: true,
          document_count: 0,
          version: 0,
        });
      }
      if (
        url.endsWith(`/api/batches/${batchId}`) &&
        init?.method !== "POST" &&
        init?.method !== "PATCH" &&
        init?.method !== "DELETE"
      ) {
        return json({
          batch_id: batchId,
          state: "finished",
          mask_salary: true,
          document_count: 1,
          version: 4,
          documents: [
            documentView({
              document_id: reviewId,
              batch_id: batchId,
              state: "review_required",
              has_output: true,
              can_approve: true,
              review_reasons: ["DETECT_LOW_CONFIDENCE"],
              version: 4,
            }),
          ],
        });
      }
      if (url === `/api/batches/${batchId}/documents/${reviewId}/download`) {
        return pdfDownload(reviewId);
      }
      if (
        url === `/api/batches/${batchId}/documents/${reviewId}/approve` &&
        init?.method === "POST"
      ) {
        return json(
          documentView({
            document_id: reviewId,
            batch_id: batchId,
            state: "completed",
            has_output: true,
            version: 5,
          }),
        );
      }
      throw new Error(`unexpected ${url}`);
    });
    renderAfterUpload(fetchMock);
    await waitFor(() => {
      expect(
        screen.getByRole("button", { name: viCopy.view }),
      ).toBeInTheDocument();
    });
    fireEvent.click(screen.getByRole("button", { name: viCopy.view }));
    const dialog = await screen.findByRole("dialog");
    expect(
      within(dialog).getByRole("button", { name: viCopy.keep }),
    ).toBeInTheDocument();
    expect(
      within(dialog).getByRole("button", { name: viCopy.deny }),
    ).toBeInTheDocument();
    fireEvent.click(within(dialog).getByRole("button", { name: viCopy.keep }));
    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith(
        `/api/batches/${batchId}/documents/${reviewId}/approve`,
        expect.objectContaining({ method: "POST" }),
      );
    });
    createObjectURL.mockRestore();
    revokeObjectURL.mockRestore();
  });
});

function pdfDownload(documentId: string): Response {
  return new Response("%PDF-synthetic-masked\n", {
    status: 200,
    headers: {
      "Content-Type": "application/pdf",
      "Content-Disposition": `attachment; filename="redacted-${documentId}.pdf"`,
    },
  });
}

function renderAfterUpload(
  fetchMock: ReturnType<typeof vi.fn>,
  filename = "synthetic-ok.pdf",
  type = "application/pdf",
): void {
  vi.stubGlobal("fetch", fetchMock);
  const xhr = mockXhr(
    documentView({
      document_id: "00000000-0000-4000-8000-0000000000d1",
      batch_id: "00000000-0000-4000-8000-0000000000aa",
      state: "uploaded",
      version: 1,
    }),
  );
  vi.stubGlobal("XMLHttpRequest", xhr.ctor);
  render(<App />);
  const input = document.querySelector('input[type="file"]');
  fireEvent.change(input as HTMLInputElement, {
    target: {
      files: [new File(["%PDF-synthetic\n"], filename, { type })],
    },
  });
}

function documentView(overrides: Partial<DocumentView>): DocumentView {
  return {
    document_id: "00000000-0000-4000-8000-0000000000d0",
    batch_id: "00000000-0000-4000-8000-0000000000aa",
    state: "uploaded",
    document_format: "pdf",
    size_bytes: 12,
    attempt: 0,
    error_code: null,
    review_reasons: [] as string[],
    can_approve: false,
    has_output: false,
    finding_counts: null,
    hidden_removed: {},
    residual_counts: {},
    residual_pages: {},
    version: 1,
    ...overrides,
  };
}

function requestUrl(input: RequestInfo | URL): string {
  if (typeof input === "string") {
    return input;
  }
  if (input instanceof URL) {
    return input.href;
  }
  return input.url;
}

function captureDownloads(): {
  names: string[];
  blobs: Blob[];
  restore: () => void;
} {
  const names: string[] = [];
  const blobs: Blob[] = [];
  const click = vi
    .spyOn(HTMLAnchorElement.prototype, "click")
    .mockImplementation(function (this: HTMLAnchorElement) {
      names.push(this.download);
    });
  const create = vi.spyOn(URL, "createObjectURL").mockImplementation((blob) => {
    if (blob instanceof Blob) {
      blobs.push(blob);
    }
    return "blob:http://127.0.0.1/synthetic-download";
  });
  const revoke = vi
    .spyOn(URL, "revokeObjectURL")
    .mockImplementation(() => undefined);
  return {
    names,
    blobs,
    restore: () => {
      click.mockRestore();
      create.mockRestore();
      revoke.mockRestore();
    },
  };
}

function zipEntryNames(bytes: Uint8Array): string[] {
  const names: string[] = [];
  const decoder = new TextDecoder();
  let offset = 0;
  while (offset + 30 <= bytes.byteLength) {
    const view = new DataView(bytes.buffer, bytes.byteOffset + offset);
    if (view.getUint32(0, true) !== 0x04034b50) {
      break;
    }
    const size = view.getUint32(18, true);
    const nameLen = view.getUint16(26, true);
    const extraLen = view.getUint16(28, true);
    names.push(decoder.decode(bytes.slice(offset + 30, offset + 30 + nameLen)));
    offset += 30 + nameLen + extraLen + size;
  }
  return names;
}

function json(body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { "Content-Type": "application/json" },
  });
}

function jsonStatus(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function mockXhr(response: unknown): {
  ctor: typeof XMLHttpRequest;
  opened: string[];
  setResponse: (next: unknown) => void;
} {
  const opened: string[] = [];
  let current = response;
  class FakeXHR {
    status = 201;
    response = current;
    upload = {
      onprogress: null as ((event: ProgressEvent) => void) | null,
    };
    onload: (() => void) | null = null;
    onerror: (() => void) | null = null;
    open(_method: string, url: string): void {
      opened.push(url);
    }
    setRequestHeader(): void {
      return;
    }
    send(): void {
      this.response = current;
      this.onload?.();
    }
  }
  return {
    ctor: FakeXHR as unknown as typeof XMLHttpRequest,
    opened,
    setResponse: (next: unknown) => {
      current = next;
    },
  };
}

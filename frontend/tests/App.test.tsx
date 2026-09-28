import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { App } from "../src/App";
import { MESSAGES, messageForCode, messageForState } from "../src/i18n";
import type { DocumentView } from "../src/types";

const viCopy = MESSAGES.vi;
const enCopy = MESSAGES.en;

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
  });

  it("switches to English without remote assets", () => {
    render(<App />);
    fireEvent.click(screen.getByRole("button", { name: viCopy.english }));
    expect(
      screen.getByRole("heading", { level: 1, name: enCopy.title }),
    ).toBeInTheDocument();
    expect(
      screen.getByText(enCopy.maskedNotice, { exact: false }),
    ).toBeInTheDocument();
    expect(document.documentElement.lang).toBe("en");
  });

  it("exposes salary as the only optional policy control", () => {
    render(<App />);
    const boxes = screen.getAllByRole("checkbox");
    expect(boxes).toHaveLength(1);
    expect(boxes[0]).toBeChecked();
    expect(screen.getByText(viCopy.salaryHelp)).toBeInTheDocument();
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
    expect(
      screen.getByText(messageForState("vi", "uploaded")),
    ).toBeInTheDocument();
    expect(fetchMock).not.toHaveBeenCalledWith(
      expect.stringMatching(/^https?:\/\/(?!127\.0\.0\.1)/),
    );
    expect(screen.queryByText("%PDF-synthetic")).not.toBeInTheDocument();
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
              error_code: "PDF_MALFORMED",
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
      expect(screen.getByText(viCopy.exportZip)).toBeInTheDocument();
    });
    expect(
      screen.getByText(messageForState("vi", "completed")),
    ).toBeInTheDocument();
    expect(
      screen.getByText(messageForState("vi", "failed")),
    ).toBeInTheDocument();
    expect(
      screen.getByText(messageForCode("vi", "PDF_MALFORMED")),
    ).toBeInTheDocument();
    expect(
      screen.getAllByRole("button", { name: viCopy.download }),
    ).toHaveLength(1);
    expect(
      screen.getByRole("button", { name: viCopy.exportZip }),
    ).toBeInTheDocument();
    expect(screen.queryByText("%PDF-synthetic")).not.toBeInTheDocument();
  });
});

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

function json(body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { "Content-Type": "application/json" },
  });
}

function mockXhr(response: unknown): { ctor: typeof XMLHttpRequest } {
  class FakeXHR {
    status = 201;
    response = response;
    upload = {
      onprogress: null as ((event: ProgressEvent) => void) | null,
    };
    onload: (() => void) | null = null;
    onerror: (() => void) | null = null;
    open(): void {
      return;
    }
    setRequestHeader(): void {
      return;
    }
    send(): void {
      this.onload?.();
    }
  }
  return { ctor: FakeXHR as unknown as typeof XMLHttpRequest };
}

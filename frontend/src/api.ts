import type {
  ApiErrorBody,
  BatchDetail,
  BatchView,
  DocumentView,
} from "./types";

export class ApiRequestError extends Error {
  readonly code: string;
  readonly status: number;
  readonly documentId: string | undefined;
  readonly limit: number | undefined;

  constructor(status: number, body: ApiErrorBody) {
    super(body.code);
    this.name = "ApiRequestError";
    this.code = body.code;
    this.status = status;
    this.documentId = body.document_id;
    this.limit = body.limit;
  }
}

async function readError(response: Response): Promise<ApiRequestError> {
  let body: ApiErrorBody = { code: "INTERNAL_ERROR" };
  try {
    const parsed: unknown = await response.json();
    if (parsed !== null && typeof parsed === "object" && "code" in parsed) {
      const code = parsed.code;
      if (typeof code === "string") {
        body = parsed as ApiErrorBody;
      }
    }
  } catch {
    body = { code: "INTERNAL_ERROR" };
  }
  return new ApiRequestError(response.status, body);
}

async function request(url: string, init?: RequestInit): Promise<Response> {
  const response = await fetch(url, init);
  if (!response.ok) {
    throw await readError(response);
  }
  return response;
}

async function json<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await request(url, init);
  return (await response.json()) as T;
}

function versioned(expected_version: number): string {
  return JSON.stringify({ expected_version });
}

export function createBatch(maskSalary: boolean): Promise<BatchView> {
  return json("/api/batches", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ mask_salary: maskSalary }),
  });
}

export function getBatch(batchId: string): Promise<BatchDetail> {
  return json(`/api/batches/${batchId}`);
}

export function setMaskSalary(
  batchId: string,
  maskSalary: boolean,
  expectedVersion: number,
): Promise<BatchView> {
  return json(`/api/batches/${batchId}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      mask_salary: maskSalary,
      expected_version: expectedVersion,
    }),
  });
}

export function startBatch(
  batchId: string,
  expectedVersion: number,
): Promise<BatchView> {
  return json(`/api/batches/${batchId}/start`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: versioned(expectedVersion),
  });
}

export function purgeBatch(batchId: string): Promise<void> {
  return request(`/api/batches/${batchId}`, { method: "DELETE" }).then(
    () => undefined,
  );
}

export function removeDocument(
  batchId: string,
  documentId: string,
): Promise<void> {
  return request(`/api/batches/${batchId}/documents/${documentId}`, {
    method: "DELETE",
  }).then(() => undefined);
}

export function cancelDocument(
  batchId: string,
  documentId: string,
  expectedVersion: number,
): Promise<DocumentView> {
  return json(`/api/batches/${batchId}/documents/${documentId}/cancel`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: versioned(expectedVersion),
  });
}

export function approveDocument(
  batchId: string,
  documentId: string,
  expectedVersion: number,
): Promise<DocumentView> {
  return json(`/api/batches/${batchId}/documents/${documentId}/approve`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: versioned(expectedVersion),
  });
}

export function denyDocument(
  batchId: string,
  documentId: string,
  expectedVersion: number,
): Promise<DocumentView> {
  return json(`/api/batches/${batchId}/documents/${documentId}/deny`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: versioned(expectedVersion),
  });
}

export function downloadUrl(batchId: string, documentId: string): string {
  return `/api/batches/${batchId}/documents/${documentId}/download`;
}

export function exportUrl(batchId: string): string {
  return `/api/batches/${batchId}/export`;
}

export function uploadDocument(
  batchId: string,
  file: File,
  onProgress: (percent: number) => void,
): Promise<DocumentView> {
  return new Promise((resolve, reject) => {
    const body = new FormData();
    body.append("file", file);
    const xhr = new XMLHttpRequest();
    xhr.open("POST", `/api/batches/${batchId}/documents`);
    xhr.responseType = "json";
    xhr.upload.onprogress = (event) => {
      if (event.lengthComputable && event.total > 0) {
        onProgress(Math.round((event.loaded / event.total) * 100));
      }
    };
    xhr.onload = () => {
      if (xhr.status >= 200 && xhr.status < 300) {
        resolve(xhr.response as DocumentView);
        return;
      }
      const parsed: unknown = xhr.response;
      let code = "INTERNAL_ERROR";
      let documentId: string | undefined;
      if (parsed !== null && typeof parsed === "object") {
        if ("code" in parsed && typeof parsed.code === "string") {
          code = parsed.code;
        }
        if ("document_id" in parsed && typeof parsed.document_id === "string") {
          documentId = parsed.document_id;
        }
      }
      reject(
        new ApiRequestError(
          xhr.status,
          documentId === undefined
            ? { code }
            : { code, document_id: documentId },
        ),
      );
    };
    xhr.onerror = () => {
      reject(new ApiRequestError(0, { code: "INTERNAL_ERROR" }));
    };
    xhr.send(body);
  });
}

import {
  useCallback,
  useEffect,
  useId,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
  type DragEvent,
  type RefObject,
} from "react";

import {
  ApiRequestError,
  approveDocument,
  cancelDocument,
  consumeBootstrapQuery,
  createBatch,
  denyDocument,
  downloadFile,
  downloadUrl,
  fetchMaskedFile,
  getBatch,
  isPdfBlob,
  openSession,
  purgeBatch,
  removeDocument,
  saveBlob,
  setMaskSalary,
  startBatch,
  uploadDocument,
} from "./api";
import {
  ALL_MASKED_ZIP_NAME,
  maskedDownloadName,
  uniqueDownloadName,
} from "./downloadNames";
import {
  MESSAGES,
  type Language,
  loadLanguage,
  messageForCode,
  messageForReason,
  messageForState,
  saveLanguage,
} from "./i18n";
import type { BatchDetail, DocumentState, DocumentView } from "./types";
import { zipStoreBlob, type ZipEntry } from "./zip";

const POLL_MS = 1500;
const ACCEPT =
  ".pdf,.docx,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document";

type LocalFile = {
  key: string;
  file: File;
  documentId: string | null;
  progress: number;
  uploading: boolean;
  errorCode: string | null;
};

const ACTIVE: ReadonlySet<DocumentState> = new Set([
  "created",
  "uploaded",
  "validating",
  "queued",
  "processing",
  "verifying",
]);

function isOpen(batch: BatchDetail | null): boolean {
  return batch?.state === "open";
}

function canCancel(state: DocumentState): boolean {
  return state === "created" || state === "uploaded" || state === "queued";
}

function completedMasked(documents: readonly DocumentView[]): DocumentView[] {
  return documents.filter((job) => job.state === "completed" && job.has_output);
}

function canDownload(job: DocumentView): boolean {
  switch (job.state) {
    case "completed":
    case "review_required":
      return job.has_output;
    case "created":
    case "uploaded":
    case "validating":
    case "queued":
    case "processing":
    case "verifying":
    case "failed":
      return job.has_output;
    case "rejected":
    case "cancelled":
      return false;
    default: {
      const exhausted: never = job.state;
      return exhausted;
    }
  }
}

function canPreview(job: DocumentView): boolean {
  return canDownload(job) && job.document_format === "pdf";
}

type PdfPreview = {
  job: DocumentView;
  label: string;
  objectUrl: string | null;
  failed: boolean;
};

function countsList(
  counts: Record<string, number> | null,
  labels: Record<string, string>,
): string {
  if (counts === null) {
    return "—";
  }
  const parts = Object.entries(counts)
    .filter(([, count]) => count > 0)
    .map(([key, count]) => `${labels[key] ?? key} ${String(count)}`);
  return parts.length === 0 ? "—" : parts.join(", ");
}

function residualList(
  counts: Record<string, number>,
  pages: Record<string, number[]>,
  labels: Record<string, string>,
  pageLabel: string,
): string {
  const parts = Object.entries(counts)
    .filter(([, count]) => count > 0)
    .map(([key, count]) => {
      const name = `${labels[key] ?? key} ${String(count)}`;
      const where = pages[key];
      if (where === undefined || where.length === 0) {
        return name;
      }
      return `${name} (${pageLabel} ${where.join(", ")})`;
    });
  return parts.join(", ");
}

function newKey(): string {
  return crypto.randomUUID();
}

export function App() {
  const fileInputId = useId();
  const [language, setLanguage] = useState<Language>(loadLanguage);
  const [batch, setBatch] = useState<BatchDetail | null>(null);
  const [locals, setLocals] = useState<LocalFile[]>([]);
  const [maskSalary, setMaskSalaryState] = useState(true);
  const [busy, setBusy] = useState(false);
  const [exporting, setExporting] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const [dragging, setDragging] = useState(false);
  const t = MESSAGES[language];

  useEffect(() => {
    document.documentElement.lang = language;
    document.title = t.title;
    saveLanguage(language);
  }, [language, t.title]);

  useEffect(() => {
    const bootstrap = consumeBootstrapQuery(window.location.search, (path) => {
      window.history.replaceState(null, "", path);
    });
    void openSession(bootstrap).catch((error: unknown) => {
      setNotice(
        error instanceof ApiRequestError
          ? messageForCode(loadLanguage(), error.code)
          : (loadLanguage() === "en" ? MESSAGES.en : MESSAGES.vi).sessionFailed,
      );
    });
  }, []);

  const refresh = useCallback(async (batchId: string) => {
    const detail = await getBatch(batchId);
    setBatch(detail);
    setMaskSalaryState(detail.mask_salary);
    return detail;
  }, []);

  useEffect(() => {
    if (batch === null) {
      return;
    }
    const inFlight = batch.documents.some((job) => ACTIVE.has(job.state));
    if (batch.state !== "running" && !inFlight) {
      return;
    }
    const id = window.setInterval(() => {
      void refresh(batch.batch_id).catch((error: unknown) => {
        if (error instanceof ApiRequestError && error.status === 404) {
          setBatch(null);
        }
      });
    }, POLL_MS);
    return () => {
      window.clearInterval(id);
    };
  }, [batch, refresh]);

  const names = useMemo(() => {
    const map = new Map<string, string>();
    for (const item of locals) {
      if (item.documentId !== null) {
        map.set(item.documentId, item.file.name);
      }
    }
    return map;
  }, [locals]);

  const changeLanguage = (next: Language): void => {
    setLanguage(next);
  };

  const ensureBatch = async (): Promise<BatchDetail> => {
    if (batch !== null && batch.state === "open") {
      return batch;
    }
    const created = await createBatch(maskSalary);
    const detail = await refresh(created.batch_id);
    return detail;
  };

  const applyFiles = async (list: File[]): Promise<void> => {
    if (list.length === 0) {
      return;
    }
    setNotice(null);
    const current = await ensureBatch();
    for (const file of list) {
      const key = newKey();
      setLocals((rows) => [
        ...rows,
        {
          key,
          file,
          documentId: null,
          progress: 0,
          uploading: true,
          errorCode: null,
        },
      ]);
      try {
        const uploaded = await uploadDocument(
          current.batch_id,
          file,
          (percent) => {
            setLocals((rows) =>
              rows.map((row) =>
                row.key === key ? { ...row, progress: percent } : row,
              ),
            );
          },
        );
        setLocals((rows) =>
          rows.map((row) =>
            row.key === key
              ? {
                  ...row,
                  documentId: uploaded.document_id,
                  progress: 100,
                  uploading: false,
                  errorCode: uploaded.error_code,
                }
              : row,
          ),
        );
      } catch (error: unknown) {
        const code =
          error instanceof ApiRequestError ? error.code : "INTERNAL_ERROR";
        const documentId =
          error instanceof ApiRequestError ? (error.documentId ?? null) : null;
        setLocals((rows) =>
          rows.map((row) =>
            row.key === key
              ? { ...row, documentId, uploading: false, errorCode: code }
              : row,
          ),
        );
      }
      await refresh(current.batch_id);
    }
  };

  const onDrop = (event: DragEvent<HTMLElement>): void => {
    event.preventDefault();
    setDragging(false);
    void applyFiles([...event.dataTransfer.files]);
  };

  const toggleSalary = async (checked: boolean): Promise<void> => {
    setMaskSalaryState(checked);
    if (batch === null || batch.state !== "open") {
      return;
    }
    const updated = await setMaskSalary(batch.batch_id, checked, batch.version);
    await refresh(updated.batch_id);
  };

  const onStart = async (): Promise<void> => {
    if (batch === null) {
      return;
    }
    setBusy(true);
    setNotice(null);
    try {
      await startBatch(batch.batch_id, batch.version);
      await refresh(batch.batch_id);
    } catch (error: unknown) {
      setNotice(
        error instanceof ApiRequestError
          ? messageForCode(language, error.code)
          : messageForCode(language, "INTERNAL_ERROR"),
      );
    } finally {
      setBusy(false);
    }
  };

  const onNewBatch = async (): Promise<void> => {
    setBusy(true);
    try {
      const created = await createBatch(maskSalary);
      setLocals([]);
      await refresh(created.batch_id);
    } finally {
      setBusy(false);
    }
  };

  const onPurge = async (): Promise<void> => {
    if (batch === null) {
      return;
    }
    setBusy(true);
    try {
      await purgeBatch(batch.batch_id);
      setBatch(null);
      setLocals([]);
    } finally {
      setBusy(false);
    }
  };

  const fileFor = (documentId: string): File | undefined =>
    locals.find((row) => row.documentId === documentId)?.file;

  const retry = async (documentId: string): Promise<void> => {
    const file = fileFor(documentId);
    if (file === undefined || batch === null) {
      setNotice(t.retryMissing);
      return;
    }
    setBusy(true);
    setNotice(null);
    try {
      const uploaded = await uploadDocument(
        batch.batch_id,
        file,
        () => undefined,
        documentId,
      );
      setLocals((rows) =>
        rows.map((row) =>
          row.documentId === documentId
            ? {
                ...row,
                documentId: uploaded.document_id,
                progress: 100,
                uploading: false,
                errorCode: uploaded.error_code,
              }
            : row,
        ),
      );
      await refresh(batch.batch_id);
    } catch (error: unknown) {
      if (error instanceof ApiRequestError) {
        setNotice(messageForCode(language, error.code));
      }
    } finally {
      setBusy(false);
    }
  };

  const onDownloadAll = async (): Promise<void> => {
    if (batch === null || exporting) {
      return;
    }
    const jobs = completedMasked(batch.documents);
    if (jobs.length === 0) {
      return;
    }
    setExporting(true);
    setNotice(null);
    try {
      const used = new Set<string>();
      const entries: ZipEntry[] = [];
      for (const job of jobs) {
        const { blob } = await fetchMaskedFile(
          downloadUrl(batch.batch_id, job.document_id),
        );
        entries.push({
          name: uniqueDownloadName(
            maskedDownloadName(
              names.get(job.document_id),
              job.document_format,
              job.document_id,
            ),
            used,
          ),
          bytes: new Uint8Array(await blob.arrayBuffer()),
        });
      }
      saveBlob(zipStoreBlob(entries), ALL_MASKED_ZIP_NAME);
    } catch (error: unknown) {
      setNotice(
        error instanceof ApiRequestError
          ? messageForCode(language, error.code)
          : messageForCode(language, "INTERNAL_ERROR"),
      );
    } finally {
      setExporting(false);
    }
  };

  const completed = completedMasked(batch?.documents ?? []);

  return (
    <main className="app">
      <header className="header">
        <h1>{t.title}</h1>
        <div className="languages" role="group" aria-label={t.language}>
          <button
            type="button"
            aria-pressed={language === "vi"}
            onClick={() => {
              changeLanguage("vi");
            }}
          >
            {t.vietnamese}
          </button>
          <button
            type="button"
            aria-pressed={language === "en"}
            onClick={() => {
              changeLanguage("en");
            }}
          >
            {t.english}
          </button>
        </div>
      </header>
      <p>{t.localOnly}</p>
      <p className="notice" role="note">
        {t.maskedNotice} {t.photoNotice}
      </p>

      <section className="controls" aria-label={t.start}>
        <label className="salary">
          <input
            type="checkbox"
            checked={maskSalary}
            disabled={!isOpen(batch) && batch !== null}
            onChange={(event) => {
              void toggleSalary(event.target.checked);
            }}
          />
          {t.salary}
        </label>
        <p className="hint">{t.salaryHelp}</p>
        <div className="buttons">
          <button
            type="button"
            onClick={() => void onNewBatch()}
            disabled={busy}
          >
            {t.newBatch}
          </button>
          <button
            type="button"
            onClick={() => void onStart()}
            disabled={
              busy ||
              batch === null ||
              batch.state !== "open" ||
              batch.document_count < 1
            }
          >
            {t.start}
          </button>
          <button
            type="button"
            onClick={() => void onPurge()}
            disabled={busy || batch === null}
          >
            {t.purge}
          </button>
          {completed.length > 0 && batch !== null ? (
            <button
              type="button"
              className="button-link"
              disabled={exporting}
              onClick={() => {
                void onDownloadAll();
              }}
            >
              {exporting ? t.busy : t.downloadAll}
            </button>
          ) : null}
        </div>
      </section>

      <section
        className={dragging ? "dropzone dragging" : "dropzone"}
        aria-label={t.drop}
        onDragOver={(event) => {
          event.preventDefault();
          setDragging(true);
        }}
        onDragLeave={() => {
          setDragging(false);
        }}
        onDrop={onDrop}
      >
        <p>{t.drop}</p>
        <p className="hint">{t.dropHelp}</p>
        <label htmlFor={fileInputId} className="button-link">
          {t.browse}
        </label>
        <input
          id={fileInputId}
          type="file"
          accept={ACCEPT}
          multiple
          className="file-input"
          onChange={(event) => {
            const chosen = event.target.files;
            if (chosen !== null) {
              void applyFiles([...chosen]);
            }
            event.target.value = "";
          }}
        />
      </section>

      {notice !== null ? (
        <p className="error" role="alert">
          {notice}
        </p>
      ) : null}
      {busy ? <p role="status">{t.busy}</p> : null}

      <FileTable
        batch={batch}
        locals={locals}
        names={names}
        language={language}
        t={t}
        onCancel={async (job) => {
          if (batch === null) {
            return;
          }
          await cancelDocument(batch.batch_id, job.document_id, job.version);
          await refresh(batch.batch_id);
        }}
        onRemove={async (job) => {
          if (batch === null) {
            return;
          }
          await removeDocument(batch.batch_id, job.document_id);
          setLocals((rows) =>
            rows.filter((row) => row.documentId !== job.document_id),
          );
          await refresh(batch.batch_id);
        }}
        onRetry={(job) => retry(job.document_id)}
        onKeep={async (job) => {
          if (batch === null) {
            return;
          }
          await approveDocument(batch.batch_id, job.document_id, job.version);
          await refresh(batch.batch_id);
        }}
        onDeny={async (job) => {
          if (batch === null) {
            return;
          }
          await denyDocument(batch.batch_id, job.document_id, job.version);
          await refresh(batch.batch_id);
        }}
        onDownload={async (job) => {
          try {
            await downloadFile(
              downloadUrl(job.batch_id, job.document_id),
              maskedDownloadName(
                names.get(job.document_id),
                job.document_format,
                job.document_id,
              ),
            );
          } catch (error: unknown) {
            setNotice(
              error instanceof ApiRequestError
                ? messageForCode(language, error.code)
                : messageForCode(language, "INTERNAL_ERROR"),
            );
          }
        }}
      />
    </main>
  );
}

function FileTable({
  batch,
  locals,
  names,
  language,
  t,
  onCancel,
  onRemove,
  onRetry,
  onKeep,
  onDeny,
  onDownload,
}: {
  batch: BatchDetail | null;
  locals: LocalFile[];
  names: Map<string, string>;
  language: Language;
  t: (typeof MESSAGES)[Language];
  onCancel: (job: DocumentView) => Promise<void>;
  onRemove: (job: DocumentView) => Promise<void>;
  onRetry: (job: DocumentView) => Promise<void>;
  onKeep: (job: DocumentView) => Promise<void>;
  onDeny: (job: DocumentView) => Promise<void>;
  onDownload: (job: DocumentView) => Promise<void>;
}) {
  const pending = locals.filter((row) => row.documentId === null);
  const jobs = batch?.documents ?? [];
  const previewGeneration = useRef(0);
  const objectUrlRef = useRef<string | null>(null);
  const dialogRef = useRef<HTMLDialogElement>(null);
  const [preview, setPreview] = useState<PdfPreview | null>(null);

  const forgetObjectUrl = (): void => {
    if (objectUrlRef.current !== null) {
      URL.revokeObjectURL(objectUrlRef.current);
      objectUrlRef.current = null;
    }
  };

  const closePreview = (): void => {
    previewGeneration.current += 1;
    forgetObjectUrl();
    setPreview(null);
  };

  const openPreview = async (
    job: DocumentView,
    label: string,
  ): Promise<void> => {
    const gen = ++previewGeneration.current;
    forgetObjectUrl();
    setPreview({ job, label, objectUrl: null, failed: false });
    try {
      const { blob } = await fetchMaskedFile(
        downloadUrl(job.batch_id, job.document_id),
      );
      if (gen !== previewGeneration.current) {
        return;
      }
      if (!isPdfBlob(blob)) {
        setPreview({ job, label, objectUrl: null, failed: true });
        return;
      }
      const objectUrl = URL.createObjectURL(blob);
      objectUrlRef.current = objectUrl;
      setPreview({ job, label, objectUrl, failed: false });
    } catch {
      if (gen !== previewGeneration.current) {
        return;
      }
      setPreview({ job, label, objectUrl: null, failed: true });
    }
  };

  useLayoutEffect(() => {
    const dialog = dialogRef.current;
    if (preview === null || dialog === null || dialog.open) {
      return;
    }
    if (typeof dialog.showModal === "function") {
      try {
        dialog.showModal();
        return;
      } catch {
        // jsdom and some test hosts do not implement modal dialogs
      }
    }
    dialog.setAttribute("open", "");
  }, [preview]);

  useEffect(() => {
    const generation = previewGeneration;
    const heldUrl = objectUrlRef;
    return () => {
      generation.current += 1;
      if (heldUrl.current !== null) {
        URL.revokeObjectURL(heldUrl.current);
        heldUrl.current = null;
      }
    };
  }, []);

  if (jobs.length === 0 && pending.length === 0) {
    return <p>{t.empty}</p>;
  }
  return (
    <>
      <table>
        <thead>
          <tr>
            <th scope="col">{t.file}</th>
            <th scope="col">{t.status}</th>
            <th scope="col">{t.findings}</th>
            <th scope="col">{t.hidden}</th>
            <th scope="col">{t.actions}</th>
          </tr>
        </thead>
        <tbody>
          {pending.map((row) => (
            <tr key={row.key}>
              <td>{row.file.name}</td>
              <td>
                {row.uploading
                  ? `${t.uploading} ${String(row.progress)}%`
                  : row.errorCode !== null
                    ? messageForCode(language, row.errorCode)
                    : "—"}
              </td>
              <td>—</td>
              <td>—</td>
              <td />
            </tr>
          ))}
          {jobs.map((job) => {
            const label =
              names.get(job.document_id) ??
              job.document_format ??
              job.document_id.slice(0, 8);
            return (
              <tr key={job.document_id}>
                <td>{label}</td>
                <td>
                  <div>{messageForState(language, job.state)}</div>
                  {job.error_code !== null ? (
                    <div>{messageForCode(language, job.error_code)}</div>
                  ) : null}
                  {Object.keys(job.residual_counts).length > 0 ? (
                    <div className="residual">
                      {t.residual}{" "}
                      {residualList(
                        job.residual_counts,
                        job.residual_pages,
                        t.entities,
                        t.residualPage,
                      )}
                    </div>
                  ) : null}
                  {job.review_reasons.map((reason) => (
                    <div key={reason}>{messageForReason(language, reason)}</div>
                  ))}
                </td>
                <td>{countsList(job.finding_counts, t.entities)}</td>
                <td>{countsList(job.hidden_removed, t.hiddenKinds)}</td>
                <td className="actions">
                  {canCancel(job.state) ? (
                    <button type="button" onClick={() => void onCancel(job)}>
                      {t.cancel}
                    </button>
                  ) : null}
                  {isOpen(batch) ? (
                    <button type="button" onClick={() => void onRemove(job)}>
                      {t.remove}
                    </button>
                  ) : null}
                  {job.state === "failed" && names.has(job.document_id) ? (
                    <button type="button" onClick={() => void onRetry(job)}>
                      {t.retry}
                    </button>
                  ) : null}
                  {canPreview(job) ? (
                    <button
                      type="button"
                      onClick={() => void openPreview(job, label)}
                    >
                      {t.view}
                    </button>
                  ) : null}
                  {canDownload(job) ? (
                    <button type="button" onClick={() => void onDownload(job)}>
                      {t.download}
                    </button>
                  ) : null}
                  {job.can_approve ? (
                    <button type="button" onClick={() => void onKeep(job)}>
                      {t.keep}
                    </button>
                  ) : null}
                  {job.state === "review_required" ? (
                    <button type="button" onClick={() => void onDeny(job)}>
                      {t.deny}
                    </button>
                  ) : null}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
      {preview !== null ? (
        <MaskedPdfDialog
          dialogRef={dialogRef}
          preview={preview}
          t={t}
          onClose={closePreview}
          onKeep={onKeep}
          onDeny={onDeny}
        />
      ) : null}
    </>
  );
}

function MaskedPdfDialog({
  dialogRef,
  preview,
  t,
  onClose,
  onKeep,
  onDeny,
}: {
  dialogRef: RefObject<HTMLDialogElement | null>;
  preview: PdfPreview;
  t: (typeof MESSAGES)[Language];
  onClose: () => void;
  onKeep: (job: DocumentView) => Promise<void>;
  onDeny: (job: DocumentView) => Promise<void>;
}) {
  const headingId = useId();
  const requestClose = (): void => {
    const dialog = dialogRef.current;
    if (dialog !== null && dialog.open && typeof dialog.close === "function") {
      dialog.close();
    }
    onClose();
  };
  return (
    <dialog
      ref={dialogRef}
      className="preview-dialog"
      aria-labelledby={headingId}
      onClose={onClose}
    >
      <div className="preview-toolbar">
        <h2 id={headingId}>{t.preview}</h2>
        <p className="preview-filename">{preview.label}</p>
        <button type="button" onClick={requestClose}>
          {t.closePreview}
        </button>
      </div>
      {preview.failed ? (
        <p className="error preview-status" role="alert">
          {t.previewFailed}
        </p>
      ) : null}
      {!preview.failed && preview.objectUrl === null ? (
        <p className="preview-status" role="status">
          {t.previewLoading}
        </p>
      ) : null}
      {preview.job.state === "failed" ? (
        <p className="error preview-status" role="alert">
          {t.unsafeOutput}
          {Object.keys(preview.job.residual_counts).length > 0
            ? ` ${residualList(
                preview.job.residual_counts,
                preview.job.residual_pages,
                t.entities,
                t.residualPage,
              )}`
            : ""}
        </p>
      ) : null}
      {preview.objectUrl !== null ? (
        <iframe
          className="preview-frame"
          title={t.preview}
          src={preview.objectUrl}
        />
      ) : null}
      {preview.job.state === "review_required" ? (
        <div className="actions preview-review">
          {preview.job.can_approve ? (
            <button
              type="button"
              onClick={() => {
                const job = preview.job;
                requestClose();
                void onKeep(job);
              }}
            >
              {t.keep}
            </button>
          ) : null}
          <button
            type="button"
            onClick={() => {
              const job = preview.job;
              requestClose();
              void onDeny(job);
            }}
          >
            {t.deny}
          </button>
        </div>
      ) : null}
    </dialog>
  );
}

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
  fetchInputFile,
  fetchMaskedFile,
  getBatch,
  importSourceLink,
  isPdfBlob,
  openSession,
  removeDocument,
  saveBlob,
  setMaskSalary,
  startBatch,
  uploadDocument,
} from "./api";
import { isDownloadableCvUrl } from "./cvDownload";
import {
  bulkZipName,
  candidateArchiveLayout,
  cvFilesFrom,
  maskedDownloadName,
  maskedOnlyPath,
} from "./downloadNames";
import {
  MESSAGES,
  messageForCode,
  messageForReason,
  messageForState,
} from "./i18n";
import type { BatchDetail, DocumentState, DocumentView } from "./types";
import { parseSourceLinks } from "./urlList";
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

function bulkDownloadable(job: DocumentView): boolean {
  return canDownload(job) && job.error_code !== "REDACT_SANITIZE_FAILED";
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

function fill(
  template: string,
  values: Readonly<Record<string, string>>,
): string {
  return template.replace(
    /\{(\w+)\}/g,
    (match, key: string) => values[key] ?? match,
  );
}

export function App() {
  const fileInputId = useId();
  const folderInputId = useId();
  const urlListId = useId();
  const [batch, setBatch] = useState<BatchDetail | null>(null);
  const [locals, setLocals] = useState<LocalFile[]>([]);
  const [urlDraft, setUrlDraft] = useState("");
  const [maskSalary, setMaskSalaryState] = useState(true);
  const [busy, setBusy] = useState(false);
  const [exporting, setExporting] = useState<"all" | "masked" | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [dragging, setDragging] = useState(false);
  const [downloadHint, setDownloadHint] = useState<string | null>(null);
  const [linkNames, setLinkNames] = useState<ReadonlyMap<string, string>>(
    () => new Map(),
  );
  const t = MESSAGES;

  useEffect(() => {
    document.documentElement.lang = "vi";
    document.title = t.title;
  }, [t.title]);

  useEffect(() => {
    const bootstrap = consumeBootstrapQuery(window.location.search, (path) => {
      window.history.replaceState(null, "", path);
    });
    void openSession(bootstrap).catch((error: unknown) => {
      setNotice(
        error instanceof ApiRequestError
          ? messageForCode(error.code)
          : t.sessionFailed,
      );
    });
  }, [t.sessionFailed]);

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
    const map = new Map(linkNames);
    for (const item of locals) {
      if (item.documentId !== null) {
        map.set(item.documentId, item.file.name);
      }
    }
    return map;
  }, [linkNames, locals]);

  const sourceLinks = useMemo(() => parseSourceLinks(urlDraft), [urlDraft]);
  const downloadableLinks = useMemo(
    () => sourceLinks.filter((link) => isDownloadableCvUrl(link.href)),
    [sourceLinks],
  );
  const ensureBatch = async (): Promise<BatchDetail> => {
    if (batch !== null && batch.state === "open") {
      return batch;
    }
    const created = await createBatch(maskSalary);
    const detail = await refresh(created.batch_id);
    return detail;
  };

  const applyFiles = async (list: File[]): Promise<void> => {
    const files = cvFilesFrom(list);
    if (files.length === 0) {
      if (list.length > 0) {
        setNotice(t.noCvInFolder);
      }
      return;
    }
    setNotice(null);
    const current = await ensureBatch();
    for (const file of files) {
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

  const onDownloadLinks = (): void => {
    if (busy || downloadableLinks.length < 1) {
      return;
    }
    const links = downloadableLinks;
    setBusy(true);
    setNotice(null);
    setDownloadHint(null);
    void (async () => {
      const failed: string[] = [];
      try {
        const current = await ensureBatch();
        for (let index = 0; index < links.length; index += 1) {
          const link = links[index];
          if (link === undefined) {
            continue;
          }
          setDownloadHint(
            fill(t.downloadProgress, {
              current: String(index + 1),
              total: String(links.length),
            }),
          );
          try {
            const uploaded = await importSourceLink(
              current.batch_id,
              link.href,
            );
            setLinkNames((prev) =>
              new Map(prev).set(uploaded.document_id, link.label),
            );
            const original = await fetchInputFile(
              current.batch_id,
              uploaded.document_id,
            );
            const file = new File([original], link.label, {
              type: original.type,
            });
            setLocals((rows) => [
              ...rows,
              {
                key: newKey(),
                file,
                documentId: uploaded.document_id,
                progress: 100,
                uploading: false,
                errorCode: null,
              },
            ]);
          } catch (error: unknown) {
            const code =
              error instanceof ApiRequestError ? error.code : "INTERNAL_ERROR";
            failed.push(`${link.label} (${messageForCode(code)})`);
            if (
              code === "UPLOAD_BATCH_FILE_LIMIT" ||
              code === "UPLOAD_BATCH_SIZE_LIMIT" ||
              code === "UPLOAD_BATCH_CLOSED"
            ) {
              break;
            }
          }
        }
        await refresh(current.batch_id);
      } catch (error: unknown) {
        setNotice(
          error instanceof ApiRequestError
            ? messageForCode(error.code)
            : messageForCode("INTERNAL_ERROR"),
        );
      } finally {
        setDownloadHint(null);
        setBusy(false);
      }
      if (failed.length > 0) {
        setNotice(fill(t.downloadFailed, { names: failed.join(", ") }));
      }
    })();
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
          ? messageForCode(error.code)
          : messageForCode("INTERNAL_ERROR"),
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
      setUrlDraft("");
      setDownloadHint(null);
      setLinkNames(new Map());
      await refresh(created.batch_id);
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
        setNotice(messageForCode(error.code));
      }
    } finally {
      setBusy(false);
    }
  };

  const onDownloadAll = async (kind: "all" | "masked"): Promise<void> => {
    if (batch === null || exporting !== null) {
      return;
    }
    const jobs = batch.documents.filter((job) => bulkDownloadable(job));
    if (jobs.length === 0) {
      return;
    }
    setExporting(kind);
    setNotice(null);
    try {
      const used = new Set<string>();
      const entries: ZipEntry[] = [];
      for (const job of jobs) {
        const { blob } = await fetchMaskedFile(
          downloadUrl(batch.batch_id, job.document_id),
        );
        const bytes = new Uint8Array(await blob.arrayBuffer());
        const label = names.get(job.document_id);
        switch (kind) {
          case "masked":
            entries.push({
              name: maskedOnlyPath(
                label,
                job.document_format,
                job.document_id,
                used,
              ),
              bytes,
            });
            break;
          case "all": {
            const original = fileFor(job.document_id);
            const layout = candidateArchiveLayout(
              label,
              job.document_format,
              job.document_id,
              used,
            );
            if (original !== undefined) {
              entries.push({
                name: layout.originalPath,
                bytes: new Uint8Array(await original.arrayBuffer()),
              });
            }
            entries.push({
              name: layout.maskedPath,
              bytes,
            });
            break;
          }
          default: {
            const exhaustive: never = kind;
            return exhaustive;
          }
        }
      }
      saveBlob(zipStoreBlob(entries), bulkZipName(kind));
    } catch (error: unknown) {
      setNotice(
        error instanceof ApiRequestError
          ? messageForCode(error.code)
          : messageForCode("INTERNAL_ERROR"),
      );
    } finally {
      setExporting(null);
    }
  };

  const downloadable =
    batch?.documents.filter((job) => bulkDownloadable(job)) ?? [];

  return (
    <main className="app">
      <header className="header">
        <h1>{t.title}</h1>
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
          {downloadable.length > 0 && batch !== null ? (
            <>
              <button
                type="button"
                className="button-link"
                disabled={exporting !== null}
                onClick={() => {
                  void onDownloadAll("all");
                }}
              >
                {exporting === "all" ? t.busy : t.downloadAll}
              </button>
              <button
                type="button"
                className="button-link"
                disabled={exporting !== null}
                onClick={() => {
                  void onDownloadAll("masked");
                }}
              >
                {exporting === "masked" ? t.busy : t.downloadMasked}
              </button>
            </>
          ) : null}
        </div>
        {downloadable.length > 0 ? (
          <>
            <p className="hint">{t.downloadAllHelp}</p>
            <p className="hint">{t.downloadMaskedHelp}</p>
          </>
        ) : null}
      </section>

      <section className="url-import" aria-label={t.urlList}>
        <h2>{t.urlList}</h2>
        <p className="hint">{t.urlHelp}</p>
        <label htmlFor={urlListId}>{t.urlPaste}</label>
        <textarea
          id={urlListId}
          rows={4}
          value={urlDraft}
          spellCheck={false}
          autoComplete="off"
          onChange={(event) => {
            setUrlDraft(event.target.value);
          }}
        />
        {sourceLinks.length > 0 ? (
          <ol className="url-links">
            {sourceLinks.map((link) => (
              <li key={link.href}>
                <a href={link.href} target="_blank" rel="noopener noreferrer">
                  {link.label}
                </a>
              </li>
            ))}
          </ol>
        ) : null}
        <div className="buttons">
          <button
            type="button"
            onClick={onDownloadLinks}
            disabled={busy || downloadableLinks.length < 1}
          >
            {t.downloadLinks}
          </button>
        </div>
        {downloadHint !== null ? <p role="status">{downloadHint}</p> : null}
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
        <div className="drop-actions">
          <label htmlFor={fileInputId} className="button-link">
            {t.browse}
          </label>
          <label htmlFor={folderInputId} className="button-link">
            {t.browseFolder}
          </label>
        </div>
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
        <input
          id={folderInputId}
          ref={(node) => {
            if (node !== null) {
              node.setAttribute("webkitdirectory", "");
              node.setAttribute("directory", "");
            }
          }}
          type="file"
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
                ? messageForCode(error.code)
                : messageForCode("INTERNAL_ERROR"),
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
  t: typeof MESSAGES;
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
                    ? messageForCode(row.errorCode)
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
                  <div>{messageForState(job.state)}</div>
                  {job.error_code !== null ? (
                    <div>{messageForCode(job.error_code)}</div>
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
                    <div key={reason}>{messageForReason(reason)}</div>
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
  t: typeof MESSAGES;
  onClose: () => void;
  onKeep: (job: DocumentView) => Promise<void>;
  onDeny: (job: DocumentView) => Promise<void>;
}) {
  const headingId = useId();
  const stageRef = useRef<HTMLDivElement>(null);
  const frameRef = useRef<HTMLIFrameElement>(null);
  useLayoutEffect(() => {
    const dialog = dialogRef.current;
    const stage = stageRef.current;
    const frame = frameRef.current;
    const objectUrl = preview.objectUrl;
    if (stage === null || frame === null || objectUrl === null) {
      return;
    }
    if (dialog !== null && !dialog.open) {
      if (typeof dialog.showModal === "function") {
        try {
          dialog.showModal();
        } catch {
          dialog.setAttribute("open", "");
        }
      } else {
        dialog.setAttribute("open", "");
      }
    }
    if (dialog !== null) {
      dialog.style.display = "flex";
      dialog.style.flexDirection = "column";
      dialog.style.boxSizing = "border-box";
      dialog.style.overflow = "hidden";
      dialog.style.width = "min(56rem, 96vw)";
      dialog.style.height = "90vh";
      dialog.style.maxHeight = "calc(100vh - 2rem)";
    }
    // Safari's PDF plugin keeps the viewport it had when src was set.
    // Give it the stage's pixel size first, or the page stays a short band.
    const canDeferSrc = typeof ResizeObserver === "function";
    const applySize = (): boolean => {
      const bounds = stage.getBoundingClientRect();
      const width = Math.round(bounds.width);
      const height = Math.round(bounds.height);
      if (width < 2 || height < 2) {
        return false;
      }
      frame.width = String(width);
      frame.height = String(height);
      frame.style.width = `${String(width)}px`;
      frame.style.height = `${String(height)}px`;
      return true;
    };
    const publish = (): void => {
      const before = Number(frame.height);
      const sized = applySize();
      if (!sized && canDeferSrc) {
        return;
      }
      const next = Number(frame.height);
      if (
        frame.getAttribute("src") !== objectUrl ||
        (sized && next > before + 20)
      ) {
        frame.src = objectUrl;
      }
    };
    publish();
    if (!canDeferSrc) {
      return;
    }
    const observer = new ResizeObserver(() => {
      publish();
    });
    observer.observe(stage);
    return () => {
      observer.disconnect();
    };
  }, [dialogRef, preview.objectUrl]);
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
        <div className="preview-stage" ref={stageRef}>
          <iframe ref={frameRef} className="preview-frame" title={t.preview} />
        </div>
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

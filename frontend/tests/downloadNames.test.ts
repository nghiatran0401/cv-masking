import { describe, expect, it } from "vitest";

import {
  ALL_MASKED_ZIP_NAME,
  candidateArchiveLayout,
  isCvFile,
  maskedDownloadName,
  originalDownloadName,
  uniqueDownloadName,
  uniqueFolderName,
} from "../src/downloadNames";

describe("maskedDownloadName", () => {
  it("prefixes the original file name and keeps the format extension", () => {
    expect(
      maskedDownloadName(
        "synthetic-cv.pdf",
        "pdf",
        "00000000-0000-4000-8000-0000000000d1",
      ),
    ).toBe("masked_synthetic-cv.pdf");
    expect(
      maskedDownloadName(
        "synthetic-cv.docx",
        "docx",
        "00000000-0000-4000-8000-0000000000d1",
      ),
    ).toBe("masked_synthetic-cv.docx");
  });

  it("strips path segments and unsafe characters", () => {
    expect(
      maskedDownloadName(
        "../../secret:cv.pdf",
        "pdf",
        "00000000-0000-4000-8000-0000000000d1",
      ),
    ).toBe("masked_secret_cv.pdf");
  });

  it("falls back to a short id when the original name is missing", () => {
    expect(
      maskedDownloadName(
        undefined,
        "pdf",
        "abcdef01-2345-4000-8000-0000000000d1",
      ),
    ).toBe("masked_abcdef01.pdf");
  });
});

describe("originalDownloadName", () => {
  it("keeps the sanitized original name without a masked_ prefix", () => {
    expect(
      originalDownloadName(
        "ABC.pdf",
        "pdf",
        "00000000-0000-4000-8000-0000000000d1",
      ),
    ).toBe("ABC.pdf");
  });
});

describe("candidateArchiveLayout", () => {
  it("groups original and masked files under output/candidate <stem>", () => {
    const used = new Set<string>();
    expect(
      candidateArchiveLayout(
        "ABC.pdf",
        "pdf",
        "00000000-0000-4000-8000-0000000000d1",
        used,
      ),
    ).toEqual({
      originalPath: "output/candidate ABC/ABC.pdf",
      maskedPath: "output/candidate ABC/masked_ABC.pdf",
    });
  });

  it("unique-ifies candidate folders when stems collide", () => {
    const used = new Set<string>();
    const first = candidateArchiveLayout("ABC.pdf", "pdf", "aa", used);
    const second = candidateArchiveLayout("ABC.pdf", "pdf", "bb", used);
    expect(first.originalPath).toBe("output/candidate ABC/ABC.pdf");
    expect(second.originalPath).toBe("output/candidate ABC 2/ABC.pdf");
  });
});

describe("uniqueDownloadName", () => {
  it("adds a numeric suffix when two files share a name", () => {
    const used = new Set<string>();
    expect(uniqueDownloadName("masked_cv.pdf", used)).toBe("masked_cv.pdf");
    expect(uniqueDownloadName("masked_cv.pdf", used)).toBe("masked_cv-2.pdf");
  });
});

describe("uniqueFolderName", () => {
  it("adds a numeric suffix without treating the name as a file", () => {
    const used = new Set<string>();
    expect(uniqueFolderName("candidate ABC", used)).toBe("candidate ABC");
    expect(uniqueFolderName("candidate ABC", used)).toBe("candidate ABC 2");
  });
});

describe("isCvFile", () => {
  it("accepts pdf and docx and skips office lock files", () => {
    expect(isCvFile(new File(["%PDF-synthetic\n"], "synthetic-cv.pdf"))).toBe(
      true,
    );
    expect(
      isCvFile(new File(["synthetic"], "note.txt", { type: "text/plain" })),
    ).toBe(false);
    expect(isCvFile(new File(["synthetic"], ".DS_Store"))).toBe(false);
    expect(isCvFile(new File(["synthetic"], "~$draft.docx"))).toBe(false);
  });
});

describe("ALL_MASKED_ZIP_NAME", () => {
  it("does not include an original file name", () => {
    expect(ALL_MASKED_ZIP_NAME).toBe("output.zip");
  });
});

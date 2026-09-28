import { describe, expect, it } from "vitest";

import {
  ALL_MASKED_ZIP_NAME,
  maskedDownloadName,
  uniqueDownloadName,
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

describe("uniqueDownloadName", () => {
  it("adds a numeric suffix when two files share a name", () => {
    const used = new Set<string>();
    expect(uniqueDownloadName("masked_cv.pdf", used)).toBe("masked_cv.pdf");
    expect(uniqueDownloadName("masked_cv.pdf", used)).toBe("masked_cv-2.pdf");
  });
});

describe("ALL_MASKED_ZIP_NAME", () => {
  it("does not include an original file name", () => {
    expect(ALL_MASKED_ZIP_NAME).toBe("masked_cvs.zip");
  });
});

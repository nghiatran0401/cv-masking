import { describe, expect, it } from "vitest";

import { MAX_SOURCE_URLS, parseSourceLinks } from "../src/urlList";

const SAMPLE = "https://intranet.example.invalid/2026/c0/synthetic-cv.pdf";

describe("parseSourceLinks", () => {
  it("keeps http(s) links and uses the last path segment as the label", () => {
    expect(parseSourceLinks(` ${SAMPLE} \n`)).toEqual([
      { href: SAMPLE, label: "synthetic-cv.pdf" },
    ]);
  });

  it("drops javascript, data, file, and credentialed URLs", () => {
    const text = [
      "javascript:alert(1)",
      "data:text/plain,synthetic",
      "file:///tmp/synthetic-cv.pdf",
      "https://user:secret@intranet.example.invalid/synthetic-cv.pdf",
      SAMPLE,
    ].join("\n");
    expect(parseSourceLinks(text)).toEqual([
      { href: SAMPLE, label: "synthetic-cv.pdf" },
    ]);
  });

  it("deduplicates and caps the list at the batch file limit", () => {
    const many = Array.from(
      { length: MAX_SOURCE_URLS + 5 },
      (_, index) =>
        `https://intranet.example.invalid/synthetic-${String(index)}.pdf`,
    );
    many.push(many[0] ?? SAMPLE);
    const parsed = parseSourceLinks(many.join("\n"));
    expect(parsed).toHaveLength(MAX_SOURCE_URLS);
    expect(parsed[0]?.label).toBe("synthetic-0.pdf");
  });
});

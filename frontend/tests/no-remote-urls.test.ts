import { readdirSync, readFileSync, statSync } from "node:fs";
import { join, relative } from "node:path";
import { describe, expect, it } from "vitest";

const ROOT = join(import.meta.dirname, "..");
const SCANNED_ENTRIES = ["index.html", "vite.config.ts", "src"];
const URL_PATTERN = /\b[a-z][a-z0-9+.-]*:\/\/[^\s"'`)<>]+/gi;
const ALLOWED_URL = /^https?:\/\/127\.0\.0\.1(?::\d+)?(?:\/|$)/;

function listFiles(path: string): string[] {
  if (statSync(path).isDirectory()) {
    return readdirSync(path).flatMap((entry) => listFiles(join(path, entry)));
  }
  return [path];
}

describe("frontend sources", () => {
  it("reference no URL except the loopback backend", () => {
    const offenders = SCANNED_ENTRIES.flatMap((entry) =>
      listFiles(join(ROOT, entry)),
    ).flatMap((file) =>
      Array.from(readFileSync(file, "utf8").matchAll(URL_PATTERN), (match) => ({
        file: relative(ROOT, file),
        url: match[0],
      })).filter(({ url }) => !ALLOWED_URL.test(url)),
    );

    expect(offenders).toEqual([]);
  });

  it("scans at least the entry files", () => {
    const scanned = SCANNED_ENTRIES.flatMap((entry) =>
      listFiles(join(ROOT, entry)),
    ).map((file) => relative(ROOT, file));

    expect(scanned).toEqual(
      expect.arrayContaining([
        "index.html",
        "vite.config.ts",
        join("src", "main.tsx"),
      ]),
    );
  });
});

import { describe, expect, it } from "vitest";

import { crc32, zipStore } from "../src/zip";

describe("zipStore", () => {
  it("writes a store zip whose entry names and bytes round-trip", () => {
    const payload = new TextEncoder().encode("%PDF-synthetic-masked\n");
    const bytes = zipStore([
      { name: "masked_synthetic-cv.pdf", bytes: payload },
    ]);
    expect(zipMagic(bytes)).toBe("PK\u0003\u0004");
    expect(zipEntryNames(bytes)).toEqual(["masked_synthetic-cv.pdf"]);
    expect(Array.from(zipFirstFile(bytes))).toEqual(Array.from(payload));
  });

  it("uses the standard CRC-32 of 123456789", () => {
    expect(crc32(new TextEncoder().encode("123456789"))).toBe(0xcbf43926);
  });
});

function zipMagic(bytes: Uint8Array): string {
  return String.fromCharCode(...bytes.slice(0, 4));
}

function zipEntryNames(bytes: Uint8Array): string[] {
  const names: string[] = [];
  let offset = 0;
  const decoder = new TextDecoder();
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

function zipFirstFile(bytes: Uint8Array): Uint8Array {
  const view = new DataView(bytes.buffer, bytes.byteOffset);
  const size = view.getUint32(18, true);
  const nameLen = view.getUint16(26, true);
  const extraLen = view.getUint16(28, true);
  const start = 30 + nameLen + extraLen;
  return bytes.slice(start, start + size);
}

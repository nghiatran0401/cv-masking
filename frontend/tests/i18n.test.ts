import { describe, expect, it } from "vitest";

import { MESSAGES } from "../src/i18n";

describe("i18n", () => {
  it("keeps Vietnamese and English keys aligned", () => {
    expect(Object.keys(MESSAGES.en).sort()).toEqual(
      Object.keys(MESSAGES.vi).sort(),
    );
    expect(Object.keys(MESSAGES.en.states).sort()).toEqual(
      Object.keys(MESSAGES.vi.states).sort(),
    );
    expect(Object.keys(MESSAGES.en.errors).sort()).toEqual(
      Object.keys(MESSAGES.vi.errors).sort(),
    );
    expect(Object.keys(MESSAGES.en.reasons).sort()).toEqual(
      Object.keys(MESSAGES.vi.reasons).sort(),
    );
    expect(Object.keys(MESSAGES.en.entities).sort()).toEqual(
      Object.keys(MESSAGES.vi.entities).sort(),
    );
    expect(Object.keys(MESSAGES.en.hiddenKinds).sort()).toEqual(
      Object.keys(MESSAGES.vi.hiddenKinds).sort(),
    );
  });
});

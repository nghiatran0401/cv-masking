import { describe, expect, it } from "vitest";

import { MESSAGES, messageForCode, messageForState } from "../src/i18n";

describe("i18n", () => {
  it("uses Vietnamese copy only", () => {
    expect(MESSAGES.title).toBe("Che thông tin CV");
    expect(messageForState("uploaded")).toBe("Đã nhận");
    expect(messageForCode("INTERNAL_ERROR")).toBe("Lỗi nội bộ.");
    expect(MESSAGES).not.toHaveProperty("english");
    expect(MESSAGES).not.toHaveProperty("language");
  });
});

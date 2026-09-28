import { describe, expect, it, vi } from "vitest";

import { consumeBootstrapQuery } from "../src/api";

describe("consumeBootstrapQuery", () => {
  it("strips the bootstrap query and returns the token", () => {
    const replace = vi.fn();
    const token = consumeBootstrapQuery("?bootstrap=abc_def&keep=1", replace);
    expect(token).toBe("abc_def");
    expect(replace).toHaveBeenCalledWith("/?keep=1");
  });

  it("returns undefined when the query has no bootstrap", () => {
    const replace = vi.fn();
    expect(consumeBootstrapQuery("", replace)).toBeUndefined();
    expect(replace).not.toHaveBeenCalled();
  });
});

import { describe, expect, it } from "vitest";

import config, { BACKEND_ORIGIN } from "../vite.config";

describe("vite config", () => {
  it("binds the dev server to loopback on a fixed port", () => {
    expect(config.server?.host).toBe("127.0.0.1");
    expect(config.server?.port).toBe(5173);
    expect(config.server?.strictPort).toBe(true);
  });

  it("binds the preview server to loopback on a fixed port", () => {
    expect(config.preview?.host).toBe("127.0.0.1");
    expect(config.preview?.strictPort).toBe(true);
  });

  it("proxies the API only to the loopback backend", () => {
    expect(BACKEND_ORIGIN).toBe("http://127.0.0.1:8765");
    expect(config.server?.proxy).toEqual({
      "/api": { target: BACKEND_ORIGIN, changeOrigin: true },
    });
    expect(config.server?.allowedHosts).toEqual(["127.0.0.1"]);
  });
});

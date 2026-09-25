import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { App } from "../src/App";

describe("App", () => {
  it("renders the app heading", () => {
    render(<App />);

    expect(
      screen.getByRole("heading", { level: 1, name: "CV Masking" }),
    ).toBeInTheDocument();
  });

  it("states that the app is local-only", () => {
    render(<App />);

    expect(screen.getByText(/runs only on this computer/)).toBeInTheDocument();
  });
});

import { expect, test } from "@playwright/test";

test("the UI is local-only, bilingual, and salary is the only toggle", async ({
  page,
}) => {
  const remote: string[] = [];
  page.on("request", (request) => {
    const url = request.url();
    const allowed =
      url.startsWith("http://127.0.0.1:") ||
      url.startsWith("ws://127.0.0.1:") ||
      url.startsWith("blob:") ||
      url.startsWith("data:") ||
      url === "about:blank";
    if (!allowed) {
      remote.push(url);
    }
  });
  await page.goto("/");
  await expect(page.getByRole("heading", { level: 1 })).toHaveText(
    "Che thông tin CV",
  );
  await expect(
    page.getByText("CV không được gửi đi mạng", { exact: false }),
  ).toBeVisible();
  await expect(
    page.getByText("không phải ẩn danh", { exact: false }),
  ).toBeVisible();
  await expect(page.getByRole("checkbox")).toHaveCount(1);
  await expect(page.getByRole("checkbox")).toBeChecked();
  await expect(
    page.getByRole("button", { name: "Bắt đầu che" }),
  ).toBeDisabled();
  await expect(page.getByText("Chọn thư mục", { exact: true })).toBeVisible();
  await expect(page.getByLabel("Dán URL, mỗi dòng một liên kết")).toBeVisible();
  await expect(
    page.getByText("Không lấy CV từ liên kết mạng", { exact: false }),
  ).toBeVisible();
  await page.getByRole("button", { name: "English" }).click();
  await expect(page.getByRole("heading", { level: 1 })).toHaveText(
    "CV masking",
  );
  await expect(
    page.getByText("masked, not anonymized", { exact: false }),
  ).toBeVisible();
  expect(remote).toEqual([]);
});

test("a dropped synthetic PDF keeps its display name in the table", async ({
  page,
}) => {
  await page.goto("/");
  const input = page.getByLabel("Chọn tệp");
  await input.setInputFiles({
    name: "synthetic-cv.pdf",
    mimeType: "application/pdf",
    buffer: Buffer.from("%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF\n"),
  });
  await expect(
    page.getByRole("cell", { name: "synthetic-cv.pdf" }),
  ).toBeVisible({ timeout: 30_000 });
  await expect(page.getByRole("button", { name: "Bắt đầu che" })).toBeEnabled();
});

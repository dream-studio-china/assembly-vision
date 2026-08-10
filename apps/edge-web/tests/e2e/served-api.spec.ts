import { createServer } from "node:net";
import { spawn } from "node:child_process";
import { randomUUID } from "node:crypto";
import { mkdtempSync, mkdirSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";

import { expect, test } from "@playwright/test";

function freePort(): Promise<number> {
  return new Promise((resolvePort, reject) => {
    const server = createServer();
    server.on("error", reject);
    server.listen(0, "127.0.0.1", () => {
      const address = server.address();
      if (address && typeof address === "object") {
        const port = address.port;
        server.close(() => resolvePort(port));
      } else {
        server.close(() => reject(new Error("no port")));
      }
    });
  });
}

function uuid(): string {
  return randomUUID();
}

function makeRecord(
  inspectionId: string,
  decision: Record<string, unknown> = {
    internal_decision: "OK",
    business_result: "OK",
    missing_components: [],
    low_confidence_components: [],
    reason_codes: [],
  },
): Record<string, unknown> {
  const now = new Date().toISOString();
  return {
    inspection_id: inspectionId,
    device_id: uuid(),
    device_sequence: 1,
    lifecycle_status: "COMPLETED",
    started_at: now,
    completed_at: now,
    barcode_result: { status: "READ", value: "SN-E2E-REAL", symbology: null },
    product_resolution: {
      status: "RESOLVED",
      source: "CONFIGURED_DEFAULT",
      product_code: "model_a",
      product_version_id: null,
    },
    frame_quality_summary: {
      total_frame_count: 1,
      usable_frame_count: 1,
      rejected_frame_count: 0,
      reasons: [],
    },
    application_version: "0.1.0",
    product_model_version_id: uuid(),
    product_model_checksum_sha256: "0".repeat(64),
    component_model_version_id: uuid(),
    component_model_checksum_sha256: "0".repeat(64),
    rule_version_id: uuid(),
    aggregation_policy_version: "single-frame-mvp-1",
    evidence: [],
    decision: { ...decision, decided_at: now },
    synchronization_status: "LOCAL_ONLY",
    processing_ms: 10,
    media: [
      {
        media_id: uuid(),
        kind: "KEY_FRAME",
        lifecycle: "PURGED",
        relative_path: `${inspectionId}/purged.jpg`,
        mime_type: "image/jpeg",
        size_bytes: 0,
        checksum_sha256: "0".repeat(64),
      },
      {
        media_id: uuid(),
        kind: "PRODUCT_ROI",
        lifecycle: "AVAILABLE",
        relative_path: `${inspectionId}/missing-roi.jpg`,
        mime_type: "image/jpeg",
        size_bytes: 1,
        checksum_sha256: "0".repeat(64),
      },
    ],
  };
}

async function waitForHealth(port: number): Promise<void> {
  const url = `http://127.0.0.1:${port}/api/v1/health/live`;
  const deadline = Date.now() + 30_000;
  while (Date.now() < deadline) {
    try {
      const response = await fetch(url);
      if (response.ok) return;
    } catch {
      // server not up yet
    }
    await new Promise((r) => setTimeout(r, 250));
  }
  throw new Error(`edge service did not become healthy on port ${port}`);
}

test("served dashboard shows a real reconciled inspection from the same-origin API", async ({
  page,
}) => {
  const repoRoot = resolve(process.cwd(), "..", "..");
  const root = mkdtempSync(join(tmpdir(), "av-serve-e2e-"));
  const output = join(root, "out");
  mkdirSync(output, { recursive: true });
  const inspectionId = uuid();
  const directory = join(output, inspectionId);
  mkdirSync(directory);
  writeFileSync(join(directory, "inspection.json"), JSON.stringify(makeRecord(inspectionId)));

  // A second, NG inspection feeds the default review queue (NG/open) so the
  // queue page can be asserted without changing its filters.
  const ngInspectionId = uuid();
  const ngDirectory = join(output, ngInspectionId);
  mkdirSync(ngDirectory);
  const ngRecord = makeRecord(ngInspectionId, {
    internal_decision: "NG",
    business_result: "NG",
    missing_components: ["component_a"],
    low_confidence_components: [],
    reason_codes: ["COMPONENT_MISSING:component_a"],
  });
  ngRecord.barcode_result = { status: "READ", value: "SN-E2E-NG", symbology: null };
  writeFileSync(join(ngDirectory, "inspection.json"), JSON.stringify(ngRecord));

  const port = await freePort();
  const dist = join(repoRoot, "apps", "edge-web", "dist");
  const proc = spawn(
    "uv",
    [
      "run",
      "assemblyvision",
      "serve",
      "--output",
      output,
      "--db",
      join(root, "edge.sqlite3"),
      "--static",
      dist,
      "--api-token",
      "test-edge-token",
      "--host",
      "127.0.0.1",
      "--port",
      String(port),
    ],
    { cwd: repoRoot, stdio: "ignore", env: process.env },
  );
  try {
    await waitForHealth(port);
    await page.goto(`http://127.0.0.1:${port}/login`);
    await page.getByLabel("Viewer token").fill("test-edge-token");
    await page.getByRole("button", { name: "Sign in" }).click();
    await page.goto(`http://127.0.0.1:${port}/history`);
    await expect(page.getByText("SN-E2E-REAL")).toBeVisible();
    await page.goto(`http://127.0.0.1:${port}/statistics`);
    await expect(page.getByText("Total inspections")).toBeVisible();

    // Real mode must not mix the mock operator workflow with live state (F6).
    await page.goto(`http://127.0.0.1:${port}/`);
    await expect(page.getByText("Operator workflow is a mock demonstration")).toBeVisible();
    await expect(page.getByRole("button", { name: "Confirm result" })).toHaveCount(0);
    await expect(page.getByRole("button", { name: "Continue next inspection" })).toHaveCount(0);

    // An unavailable camera renders an explicit state, never a fabricated frame.
    await page.goto(`http://127.0.0.1:${port}/live`);
    await expect(page.getByText("No camera feed available")).toBeVisible();
    // The camera pane must stay empty; the detection-result pane may still show
    // a historical media frame, so the assertion is scoped to the camera pane.
    await expect(page.locator(".live-inspection__camera-viewer img[alt='camera preview']")).not.toBeVisible();

    await page.goto(`http://127.0.0.1:${port}/images/${inspectionId}`);
    // Purged media renders an explicit purged state, never a broken image (F14).
    await expect(page.getByText("Content is not retained")).toBeVisible();
    await expect(page.locator('img[alt="inspection media"]')).toHaveCount(0);
    // AVAILABLE metadata with a missing file must settle into an unavailable
    // state after the media endpoint returns 404, not remain as a broken image.
    await page.getByRole("tab", { name: "Product ROI" }).click();
    await expect(page.getByText("Media content unavailable")).toBeVisible();
    await expect(page.locator('img[alt="inspection media"]')).toHaveCount(0);

    // Optional human-in-the-loop review (design 24): the detail view offers a
    // review panel and a submitted disposition appears in the review queue.
    await page.goto(`http://127.0.0.1:${port}/inspections/${inspectionId}`);
    await expect(page.getByText("Human review")).toBeVisible();
    await expect(page.getByText("Optional audit review")).toBeVisible();
    const review = await page.request.post(
      `http://127.0.0.1:${port}/api/v1/inspections/${inspectionId}/reviews`,
      {
        data: {
          disposition: "CONFIRMED_OK",
          reason: "audit sampled",
          reviewer: "e2e-reviewer",
        },
        headers: { "Content-Type": "application/json" },
      },
    );
    expect(review.status()).toBe(200);
    await page.goto(`http://127.0.0.1:${port}/review`);
    // The queue loads its default NG/open view on entry (regression: the
    // initial load was missing and left the queue empty until a filter changed).
    await expect(page.getByText("SN-E2E-NG")).toBeVisible();
    await page.locator("label.el-radio-button", { hasText: "OK" }).click();
    await page.locator("label.el-radio-button", { hasText: "All states" }).click();
    await expect(page.getByText("SN-E2E-REAL")).toBeVisible();
    await expect(page.getByText("Confirmed OK")).toBeVisible();
  } finally {
    proc.kill("SIGTERM");
  }
});

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

function makeRecord(inspectionId: string): Record<string, unknown> {
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
    decision: {
      internal_decision: "OK",
      business_result: "OK",
      missing_components: [],
      low_confidence_components: [],
      reason_codes: [],
      decided_at: now,
    },
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

    // Absent media renders an unavailable state, never a fabricated frame.
    await page.goto(`http://127.0.0.1:${port}/live`);
    await expect(page.getByText("No camera feed in read-only mode")).toBeVisible();
    await expect(page.getByText("No detection image available")).toBeVisible();
    await expect(page.locator('img[alt="camera preview"]')).toHaveCount(0);

    await page.goto(`http://127.0.0.1:${port}/images/${inspectionId}`);
    // Purged media renders an explicit purged state, never a broken image (F14).
    await expect(page.getByText("Original evidence has been purged")).toBeVisible();
    await expect(page.locator('img[alt="original frame"]')).toHaveCount(0);
    await page.getByRole("tab", { name: "Detection result" }).click();
    await expect(page.getByText("No detection image available")).toBeVisible();
    await page.getByRole("tab", { name: "Annotations" }).click();
    await expect(page.getByText("No annotated image available")).toBeVisible();
  } finally {
    proc.kill("SIGTERM");
  }
});

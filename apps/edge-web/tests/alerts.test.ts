import { createPinia, setActivePinia } from "pinia";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { DeviceStatus } from "@assemblyvision/api-client";
import { useAlertsStore } from "../src/stores/alerts";

function makeStatus(overrides: Partial<DeviceStatus> = {}): DeviceStatus {
  return {
    device_id: "device-1",
    observed_at: "2026-01-01T00:00:00Z",
    operational_state: "READY",
    inspection_ready: true,
    sync_ready: true,
    camera_connected: true,
    model_loaded: true,
    central_connected: true,
    disk_free_bytes: 42 * 1024 ** 3,
    upload_pending_count: 0,
    upload_pending_bytes: 0,
    upload_oldest_pending_at: null,
    upload_attempts: 1,
    upload_successes: 1,
    upload_failures: 0,
    upload_failure_rate: 0,
    upload_last_attempt_at: null,
    upload_last_success_at: null,
    upload_last_error_code: null,
    storage_mode: "NORMAL",
    storage_total_bytes: 100 * 1024 ** 3,
    storage_free_bytes: 42 * 1024 ** 3,
    storage_free_percent: 60,
    storage_free_inodes: 1000,
    storage_inode_percent: 20,
    storage_warning_free_percent: 20,
    storage_critical_free_percent: 10,
    storage_stop_free_percent: 5,
    storage_observed_at: null,
    storage_write_fault: false,
    cpu_count: 8,
    load_1m: 1.2,
    memory_total_bytes: 16 * 1024 ** 3,
    memory_available_bytes: 8 * 1024 ** 3,
    cleanup_enabled: false,
    cleanup_eligible_count: 0,
    cleanup_eligible_bytes: 0,
    cleanup_deleting_count: 0,
    cleanup_delete_error_count: 0,
    cleanup_purged_count: 0,
    cleanup_integrity_fault_count: 0,
    cleanup_last_run_at: null,
    cleanup_last_error_code: null,
    integrity_scan_last_run_at: null,
    integrity_scan_checked: 0,
    integrity_scan_faults: 0,
    integrity_scan_checksummed: 0,
    integrity_scan_skipped: 0,
    integrity_scan_skipped_reason: null,
    integrity_verify_checksums: false,
    current_product_model_version_id: "model-product-1",
    current_component_model_version_id: "model-component-1",
    current_rule_version_id: "rule-1",
    alerts: [],
    ...overrides,
  };
}

describe("alerts store", () => {
  beforeEach(() => setActivePinia(createPinia()));

  it("derives no active alerts from a healthy status", () => {
    const store = useAlertsStore();
    store.setFromDeviceStatus(makeStatus());
    expect(store.alerts).toEqual([]);
    expect(store.history).toEqual([]);
  });

  it("creates CAMERA_DISCONNECTED with guidance when the camera is disconnected", () => {
    const store = useAlertsStore();
    store.setFromDeviceStatus(makeStatus({ camera_connected: false }));
    const alert = store.alerts.find((a) => a.code === "CAMERA_DISCONNECTED");
    expect(alert).toBeDefined();
    expect(alert?.severity).toBe("critical");
    expect(alert?.guidance).toBe("Check cable and power; administrator may request reconnect.");
  });

  it("preserves firstSeenAt across repeated updates while lastSeenAt advances", async () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-01-01T00:00:00.000Z"));
    const store = useAlertsStore();
    store.setFromDeviceStatus(makeStatus({ camera_connected: false }));
    const first = store.alerts.find((a) => a.code === "CAMERA_DISCONNECTED");
    expect(first?.firstSeenAt).toBe("2026-01-01T00:00:00.000Z");
    expect(first?.lastSeenAt).toBe("2026-01-01T00:00:00.000Z");

    vi.setSystemTime(new Date("2026-01-01T00:05:00.000Z"));
    store.setFromDeviceStatus(makeStatus({ camera_connected: false }));
    const second = store.alerts.find((a) => a.code === "CAMERA_DISCONNECTED");
    expect(second?.firstSeenAt).toBe("2026-01-01T00:00:00.000Z");
    expect(second?.lastSeenAt).toBe("2026-01-01T00:05:00.000Z");
    vi.useRealTimers();
  });

  it("moves an alert to history with cleared=true when its condition clears", () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-01-01T00:00:00.000Z"));
    const store = useAlertsStore();
    store.setFromDeviceStatus(makeStatus({ camera_connected: false }));

    vi.setSystemTime(new Date("2026-01-01T00:05:00.000Z"));
    store.setFromDeviceStatus(makeStatus());
    expect(store.alerts.some((a) => a.code === "CAMERA_DISCONNECTED")).toBe(false);
    const cleared = store.history.find((a) => a.code === "CAMERA_DISCONNECTED");
    expect(cleared).toBeDefined();
    expect(cleared?.cleared).toBe(true);
    expect(cleared?.clearedAt).toBe("2026-01-01T00:05:00.000Z");
    expect(cleared?.firstSeenAt).toBe("2026-01-01T00:00:00.000Z");
    vi.useRealTimers();
  });

  it("dismiss marks a non-critical alert as cleared", () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-01-01T00:00:00.000Z"));
    const store = useAlertsStore();
    store.setFromDeviceStatus(makeStatus({ central_connected: false }));
    const alert = store.alerts.find((a) => a.code === "CENTRAL_UNREACHABLE");
    expect(alert?.severity).toBe("warning");

    vi.setSystemTime(new Date("2026-01-01T00:01:00.000Z"));
    store.dismiss(alert!.id);
    expect(store.alerts.some((a) => a.code === "CENTRAL_UNREACHABLE")).toBe(false);
    const cleared = store.history.find((a) => a.code === "CENTRAL_UNREACHABLE");
    expect(cleared).toBeDefined();
    expect(cleared?.cleared).toBe(true);
    expect(cleared?.clearedAt).toBe("2026-01-01T00:01:00.000Z");
    vi.useRealTimers();
  });
});

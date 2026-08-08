import { createPinia, setActivePinia } from "pinia";
import { beforeEach, describe, expect, it } from "vitest";
import { useAlertsStore } from "../src/stores/alerts";
import { useRuntimeStore } from "../src/stores/runtime";

describe("runtime store", () => {
  beforeEach(() => setActivePinia(createPinia()));

  it("loads device status, runtime state, and camera from the mock client", async () => {
    const store = useRuntimeStore();
    await store.refresh();
    expect(store.status?.inspection_ready).toBe(true);
    expect(store.camera?.connected).toBe(true);
    expect(store.runtime?.paused).toBe(false);
  });
});

describe("alerts store", () => {
  beforeEach(() => setActivePinia(createPinia()));

  it("derives critical and warning alerts from device status", () => {
    const store = useAlertsStore();
    store.setFromStatus(false, false, true, 40 * 1024 ** 3);
    expect(store.alerts.some((a) => a.code === "NOT_READY")).toBe(true);
    expect(store.alerts.some((a) => a.code === "CAMERA_DISCONNECTED")).toBe(true);
    expect(store.alerts.some((a) => a.code === "CENTRAL_UNREACHABLE")).toBe(false);
  });

  it("warns when disk is low and dismisses alerts", () => {
    const store = useAlertsStore();
    store.setFromStatus(true, true, true, 2 * 1024 ** 3);
    expect(store.alerts.some((a) => a.code === "DISK_LOW")).toBe(true);
    store.dismiss("disk");
    expect(store.alerts.some((a) => a.code === "DISK_LOW")).toBe(false);
  });
});

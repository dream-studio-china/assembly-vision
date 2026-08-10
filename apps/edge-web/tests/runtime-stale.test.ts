import { ApiError } from "@assemblyvision/api-client";
import type { ApiClient } from "@assemblyvision/api-client";
import { createPinia, setActivePinia } from "pinia";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { useRuntimeStore } from "../src/stores/runtime";
import { getApiClient } from "../src/services/client";

vi.mock("../src/services/client", () => ({
  getApiClient: vi.fn(),
}));

function stubClient() {
  return {
    getDeviceStatus: vi.fn().mockResolvedValue({ device_id: "device-1" }),
    getInspectionState: vi.fn().mockResolvedValue({ paused: false }),
    getCameraState: vi.fn().mockResolvedValue({
      connected: true,
      source_width: 800,
      source_height: 600,
    }),
  };
}

describe("runtime store staleness", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    vi.clearAllMocks();
  });

  it("sets lastUpdatedAt and clears error after a successful refresh", async () => {
    const client = stubClient();
    vi.mocked(getApiClient).mockReturnValue(client as unknown as ApiClient);

    const store = useRuntimeStore();
    store.error = "previous failure";

    await store.refresh();

    expect(client.getDeviceStatus).toHaveBeenCalled();
    expect(store.lastUpdatedAt).not.toBeNull();
    expect(Number.isNaN(new Date(store.lastUpdatedAt as string).getTime())).toBe(false);
    expect(store.error).toBeNull();
    expect(store.loading).toBe(false);
  });

  it("keeps the previous lastUpdatedAt and sets error after a failed refresh", async () => {
    const client = stubClient();
    client.getDeviceStatus.mockRejectedValue(new ApiError(0, "NETWORK_ERROR", "boom"));
    vi.mocked(getApiClient).mockReturnValue(client as unknown as ApiClient);

    const store = useRuntimeStore();
    const previous = "2026-01-01T00:00:00.000Z";
    store.lastUpdatedAt = previous;

    await store.refresh();

    expect(store.error).toBe("boom");
    expect(store.lastUpdatedAt).toBe(previous);
    expect(store.loading).toBe(false);
  });
});

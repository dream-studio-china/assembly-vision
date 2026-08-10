import { createPinia, setActivePinia } from "pinia";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "@assemblyvision/api-client";
import type { DeviceStatus, LogEvent, Page } from "@assemblyvision/api-client";
import { useSessionStore } from "../src/stores/session";

const mocks = vi.hoisted(() => ({
  isMockMode: vi.fn(),
  isHttpMode: vi.fn(),
  getApiClient: vi.fn(),
}));

vi.mock("../src/services/client", () => ({
  isMockMode: mocks.isMockMode,
  isHttpMode: mocks.isHttpMode,
  getApiClient: mocks.getApiClient,
}));

const deviceStatus = {} as DeviceStatus;
const logPage = { items: [], next_cursor: null } as Page<LogEvent>;

function httpClient(overrides: { status?: Error; logs?: Error } = {}) {
  mocks.isMockMode.mockReturnValue(false);
  mocks.isHttpMode.mockReturnValue(true);
  const client = {
    getDeviceStatus: vi.fn().mockResolvedValue(deviceStatus),
    listLogs: vi.fn().mockResolvedValue(logPage),
  };
  if (overrides.status) client.getDeviceStatus.mockRejectedValue(overrides.status);
  if (overrides.logs) client.listLogs.mockRejectedValue(overrides.logs);
  mocks.getApiClient.mockReturnValue(client);
  return client;
}

describe("session store", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    mocks.isMockMode.mockReset();
    mocks.isHttpMode.mockReset();
    mocks.getApiClient.mockReset();
  });

  it("mock mode grants viewer and administrator access without probing", async () => {
    mocks.isMockMode.mockReturnValue(true);
    mocks.isHttpMode.mockReturnValue(false);
    const store = useSessionStore();
    await store.check();
    expect(store.authenticated).toBe(true);
    expect(store.admin).toBe(true);
    expect(store.checked).toBe(true);
    expect(mocks.getApiClient).not.toHaveBeenCalled();
  });

  it("http mode treats a 401 device status as unauthenticated", async () => {
    const client = httpClient({ status: new ApiError(401, "UNAUTHENTICATED", "token required") });
    const store = useSessionStore();
    await store.check();
    expect(store.authenticated).toBe(false);
    expect(store.admin).toBe(false);
    expect(store.checked).toBe(true);
    expect(store.lastError).toBeNull();
    expect(client.listLogs).not.toHaveBeenCalled();
  });

  it("http mode resolves a readable device and logs as viewer + administrator", async () => {
    const client = httpClient();
    const store = useSessionStore();
    await store.check();
    expect(store.authenticated).toBe(true);
    expect(store.admin).toBe(true);
    expect(store.checked).toBe(true);
    expect(client.getDeviceStatus).toHaveBeenCalledTimes(1);
    expect(client.listLogs).toHaveBeenCalledWith(undefined, 1);
  });

  it("http mode resolves a 403 logs probe as viewer without administrator", async () => {
    const client = httpClient({ logs: new ApiError(403, "FORBIDDEN", "administrator required") });
    const store = useSessionStore();
    await store.check();
    expect(store.authenticated).toBe(true);
    expect(store.admin).toBe(false);
    expect(store.checked).toBe(true);
    expect(client.listLogs).toHaveBeenCalledTimes(1);
  });

  it("http mode treats a network failure as unauthenticated", async () => {
    const client = httpClient({ status: new ApiError(0, "NETWORK_ERROR", "request failed") });
    const store = useSessionStore();
    await store.check();
    expect(store.authenticated).toBe(false);
    expect(store.admin).toBe(false);
    expect(store.checked).toBe(true);
    expect(store.lastError).toContain("request failed");
    expect(client.listLogs).not.toHaveBeenCalled();
  });

  it("reset clears viewer and administrator flags", async () => {
    mocks.isMockMode.mockReturnValue(true);
    const store = useSessionStore();
    await store.check();
    store.reset();
    expect(store.authenticated).toBe(false);
    expect(store.admin).toBe(false);
  });
});

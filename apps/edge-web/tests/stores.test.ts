import { createPinia, setActivePinia } from "pinia";
import { beforeEach, describe, expect, it } from "vitest";
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

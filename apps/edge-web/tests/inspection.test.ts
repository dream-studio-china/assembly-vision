import { createPinia, setActivePinia } from "pinia";
import { beforeEach, describe, expect, it } from "vitest";
import { inspectionService } from "../src/services/inspectionService";
import { useInspectionStore } from "../src/stores/inspection";

describe("inspection store", () => {
  beforeEach(() => setActivePinia(createPinia()));

  it("loads the current inspection with rules", async () => {
    const store = useInspectionStore();
    await store.loadCurrent();
    expect(store.current?.status).toBe("PROCESSING");
    expect((store.current?.rules.length ?? 0)).toBeGreaterThan(0);
  });

  it("confirms and continues through the operator workflow", async () => {
    const store = useInspectionStore();
    await store.loadCurrent();

    await store.confirmResult();
    expect(["PASS", "NG"]).toContain(store.current?.status);
    expect(store.current?.progress).toBe(1);

    await store.continueNext();
    expect(store.current?.status).toBe("PROCESSING");
  });
});

describe("inspection service", () => {
  it("returns traceability and statistics from the mock layer", async () => {
    const trace = await inspectionService.getTraceability("SN-0001");
    expect(trace.attempts[0].result).toBe("NG");
    expect(trace.final_status).toBe("PASS");

    const stats = await inspectionService.getStatistics();
    expect(stats.total_inspections).toBeGreaterThan(0);
    expect(stats.pass_rate).toBeGreaterThanOrEqual(0);
  });

  it("returns image references for a known inspection", async () => {
    const page = await inspectionService.listHistory({ limit: 5 });
    const images = await inspectionService.getImages(page.items[0].inspection_id);
    expect(images.original.startsWith("data:image/svg+xml")).toBe(true);
  });
});

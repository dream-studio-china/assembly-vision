import { createPinia, setActivePinia } from "pinia";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
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

describe("inspection service cross-origin media (gap 1)", () => {
  afterEach(() => {
    vi.unstubAllEnvs();
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it("resolves token-protected media into blob URLs for cross-origin rendering", async () => {
    vi.resetModules();
    vi.stubEnv("VITE_API_MODE", "http");
    vi.stubEnv("VITE_API_BASE_URL", "http://edge-host:8000");
    vi.stubGlobal("window", { location: { origin: "http://localhost:5173" } });
    const payload = {
      inspection_id: "00000000-0000-4000-8000-0000000000dd",
      original: "http://edge-host:8000/api/v1/media/aa/content",
      detection: "",
      annotated: "http://edge-host:8000/api/v1/media/bb/content",
      original_status: "AVAILABLE",
      detection_status: "UNAVAILABLE",
      annotated_status: "AVAILABLE",
    };
    vi.stubGlobal(
      "fetch",
      (async (input: RequestInfo | URL, init?: RequestInit) => {
        const url = String(input);
        const headers = (init?.headers as Record<string, string>) ?? {};
        expect(headers["Authorization"]).toBe("Bearer secret-token");
        if (url.includes("/images")) {
          return new Response(JSON.stringify(payload), {
            status: 200,
            headers: { "Content-Type": "application/json" },
          });
        }
        return new Response(new Blob(["img"], { type: "image/jpeg" }), { status: 200 });
      }) as typeof fetch,
    );
    vi.spyOn(URL, "createObjectURL").mockReturnValue("blob:media-1");

    const { createViewerSession } = await import("../src/services/client");
    await createViewerSession("secret-token");
    const { inspectionService: svc } = await import("../src/services/inspectionService");

    const images = await svc.getImages(payload.inspection_id);
    expect(images.original).toBe("blob:media-1");
    expect(images.annotated).toBe("blob:media-1");
    expect(images.detection).toBe("");
    expect(images.detection_status).toBe("UNAVAILABLE");
  });
});

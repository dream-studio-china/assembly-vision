import { beforeEach, describe, expect, it, vi } from "vitest";
import { useReviewPanel } from "../src/composables/useReviewPanel";

const mocks = vi.hoisted(() => ({
  getApiClient: vi.fn(),
}));

vi.mock("../src/services/client", () => ({
  getApiClient: mocks.getApiClient,
}));

function reviewRecord(id: string): Record<string, unknown> {
  return {
    review_id: id,
    inspection_id: "00000000-0000-4000-8000-000000000001",
    disposition: "CONFIRMED_NG",
    reason: "defect visible",
    note: null,
    reviewer: "operator-1",
    created_at: "2026-08-10T00:00:00Z",
    original_business_result: "NG",
    original_internal_decision: "NG",
    original_reason_codes: ["COMPONENT_MISSING:component_a"],
    component_corrections: [],
    supersedes_review_id: null,
  };
}

function fillValidForm(panel: ReturnType<typeof useReviewPanel>): void {
  panel.disposition.value = "CONFIRMED_NG";
  panel.reviewer.value = "operator-1";
}

describe("useReviewPanel", () => {
  beforeEach(() => {
    mocks.getApiClient.mockReset();
  });

  it("loads history on demand and allows submission only after a successful load", async () => {
    const client = {
      listInspectionReviews: vi.fn().mockResolvedValue([reviewRecord("r-1")]),
      submitReview: vi.fn().mockResolvedValue(reviewRecord("r-2")),
    };
    mocks.getApiClient.mockReturnValue(client);
    const panel = useReviewPanel("i-1", "NG", "NG");

    fillValidForm(panel);
    // History has not loaded yet: an unseen disposition must not be silently
    // superseded (PR-031 review finding).
    expect(panel.canSubmit.value).toBe(false);

    await panel.load();

    expect(panel.historyLoaded.value).toBe(true);
    expect(panel.historyError.value).toBeNull();
    expect(panel.reviews.value).toHaveLength(1);
    expect(panel.canSubmit.value).toBe(true);

    await panel.submit();
    expect(client.submitReview).toHaveBeenCalledWith("i-1", {
      disposition: "CONFIRMED_NG",
      reviewer: "operator-1",
      reason: null,
      note: null,
    });
  });

  it("surfaces a history load failure and blocks submission", async () => {
    const client = {
      listInspectionReviews: vi.fn().mockRejectedValue(new Error("history unavailable")),
      submitReview: vi.fn(),
    };
    mocks.getApiClient.mockReturnValue(client);
    const panel = useReviewPanel("i-1", "NG", "NG");

    await panel.load();

    expect(panel.historyLoaded.value).toBe(false);
    expect(panel.historyError.value).toContain("history unavailable");
    fillValidForm(panel);
    expect(panel.canSubmit.value).toBe(false);

    await panel.submit();
    expect(client.submitReview).not.toHaveBeenCalled();
  });

  it("recovers and allows submission after a later successful history load", async () => {
    const client = {
      listInspectionReviews: vi
        .fn()
        .mockRejectedValueOnce(new Error("history unavailable"))
        .mockResolvedValueOnce([reviewRecord("r-1")]),
      submitReview: vi.fn(),
    };
    mocks.getApiClient.mockReturnValue(client);
    const panel = useReviewPanel("i-1", "NG", "NG");

    await panel.load();
    expect(panel.historyError.value).not.toBeNull();
    expect(panel.canSubmit.value).toBe(false);

    await panel.load();
    expect(panel.historyError.value).toBeNull();
    expect(panel.historyLoaded.value).toBe(true);
    fillValidForm(panel);
    expect(panel.canSubmit.value).toBe(true);
  });

  it("keeps the inconclusive reason requirement after a successful load", async () => {
    const client = {
      listInspectionReviews: vi.fn().mockResolvedValue([]),
      submitReview: vi.fn(),
    };
    mocks.getApiClient.mockReturnValue(client);
    const panel = useReviewPanel("i-1", "NG", "NG");

    await panel.load();
    panel.disposition.value = "INCONCLUSIVE";
    panel.reviewer.value = "operator-1";
    expect(panel.canSubmit.value).toBe(false);

    panel.reason.value = "insufficient evidence";
    expect(panel.canSubmit.value).toBe(true);
  });
});

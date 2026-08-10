import { computed, ref } from "vue";
import type {
  BusinessResult,
  InternalDecision,
  ReviewDisposition,
  ReviewRecord,
} from "@assemblyvision/api-client";
import { getApiClient } from "../services/client";

const ALLOWED: Record<string, ReviewDisposition[]> = {
  UNCERTAIN: ["CONFIRMED_NG", "CONFIRMED_OK", "REINSPECT", "INCONCLUSIVE"],
  NG: ["CONFIRMED_NG", "CONFIRMED_OK", "INCONCLUSIVE"],
  OK: ["CONFIRMED_OK", "CORRECTED_NG", "INCONCLUSIVE"],
};

/**
 * Review panel state (design 24 / ADR-016) extracted from the component so the
 * submit gating and history-error handling are unit-testable.
 *
 * A review may only be submitted once the append-only history has loaded
 * successfully: without it the reviewer would not see existing dispositions
 * that the submission silently supersedes (PR-031 review finding).
 */
export function useReviewPanel(
  inspectionId: string,
  businessResult: BusinessResult,
  internalDecision: InternalDecision,
) {
  const reviews = ref<ReviewRecord[]>([]);
  const loading = ref(false);
  const historyError = ref<string | null>(null);
  const historyLoaded = ref(false);
  const submitting = ref(false);
  const submitError = ref<string | null>(null);
  const submitOk = ref(false);

  const disposition = ref<ReviewDisposition | null>(null);
  const reviewer = ref("");
  const reason = ref("");
  const note = ref("");

  const allowed = computed<ReviewDisposition[]>(() =>
    internalDecision === "UNCERTAIN"
      ? ALLOWED.UNCERTAIN
      : businessResult === "NG"
        ? ALLOWED.NG
        : ALLOWED.OK,
  );

  const needsReason = computed(() => disposition.value === "INCONCLUSIVE");

  const canSubmit = computed(
    () =>
      disposition.value !== null &&
      reviewer.value.trim().length > 0 &&
      (!needsReason.value || reason.value.trim().length > 0) &&
      historyLoaded.value &&
      historyError.value === null &&
      !loading.value,
  );

  async function load(): Promise<void> {
    loading.value = true;
    historyError.value = null;
    try {
      reviews.value = await getApiClient().listInspectionReviews(inspectionId);
      historyLoaded.value = true;
    } catch (err) {
      historyLoaded.value = false;
      reviews.value = [];
      historyError.value = err instanceof Error ? err.message : String(err);
    } finally {
      loading.value = false;
    }
  }

  async function submit(): Promise<void> {
    if (!canSubmit.value || disposition.value === null) return;
    submitting.value = true;
    submitError.value = null;
    submitOk.value = false;
    try {
      await getApiClient().submitReview(inspectionId, {
        disposition: disposition.value,
        reviewer: reviewer.value.trim(),
        reason: reason.value.trim() || null,
        note: note.value.trim() || null,
      });
      submitOk.value = true;
      reviewer.value = "";
      reason.value = "";
      note.value = "";
      disposition.value = null;
      await load();
    } catch (err) {
      submitError.value = err instanceof Error ? err.message : String(err);
    } finally {
      submitting.value = false;
    }
  }

  return {
    reviews,
    loading,
    historyError,
    historyLoaded,
    submitting,
    submitError,
    submitOk,
    disposition,
    reviewer,
    reason,
    note,
    allowed,
    needsReason,
    canSubmit,
    load,
    submit,
  };
}

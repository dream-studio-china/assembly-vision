<script setup lang="ts">
import type {
  BusinessResult,
  InternalDecision,
  ReviewDisposition,
  ReviewRecord,
} from "@assemblyvision/api-client";
import { computed, onMounted, ref } from "vue";
import { getApiClient } from "../services/client";

// Optional human-in-the-loop review panel (docs/design/24-human-in-the-loop.md).
// Reviews are append-only dispositions over immutable evidence; they never
// rewrite the machine decision. The panel is additive: a failure to load or
// submit a review never affects the inspection detail view.

const props = defineProps<{
  inspectionId: string;
  businessResult: BusinessResult;
  internalDecision: InternalDecision;
}>();

const reviews = ref<ReviewRecord[]>([]);
const loading = ref(false);
const submitting = ref(false);
const submitError = ref<string | null>(null);
const submitOk = ref(false);

const disposition = ref<ReviewDisposition | null>(null);
const reviewer = ref("");
const reason = ref("");
const note = ref("");

const DISPOSITION_LABELS: Record<ReviewDisposition, string> = {
  CONFIRMED_NG: "Confirmed NG (defect confirmed)",
  CONFIRMED_OK: "Confirmed OK (false NG corrected)",
  CORRECTED_NG: "Corrected NG (missed defect)",
  INCONCLUSIVE: "Inconclusive (insufficient evidence)",
  REINSPECT: "Reinspect",
};

const ALLOWED: Record<string, ReviewDisposition[]> = {
  UNCERTAIN: ["CONFIRMED_NG", "CONFIRMED_OK", "REINSPECT", "INCONCLUSIVE"],
  NG: ["CONFIRMED_NG", "CONFIRMED_OK", "INCONCLUSIVE"],
  OK: ["CONFIRMED_OK", "CORRECTED_NG", "INCONCLUSIVE"],
};

const allowed = computed<ReviewDisposition[]>(() =>
  props.internalDecision === "UNCERTAIN"
    ? ALLOWED.UNCERTAIN
    : props.businessResult === "NG"
      ? ALLOWED.NG
      : ALLOWED.OK,
);

const needsReason = computed(() => disposition.value === "INCONCLUSIVE");
const canSubmit = computed(
  () =>
    disposition.value !== null &&
    reviewer.value.trim().length > 0 &&
    (!needsReason.value || reason.value.trim().length > 0),
);

async function load(): Promise<void> {
  loading.value = true;
  try {
    reviews.value = await getApiClient().listInspectionReviews(props.inspectionId);
  } catch {
    // Review is optional; keep the panel usable with an empty history.
    reviews.value = [];
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
    await getApiClient().submitReview(props.inspectionId, {
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

onMounted(load);
</script>

<template>
  <section class="review-panel">
    <h3>Human review</h3>
    <el-alert
      v-if="props.businessResult === 'NG'"
      title="This inspection can be reviewed"
      description="Review the machine decision against the retained evidence and record a disposition. The machine decision is never rewritten."
      type="warning"
      show-icon
      :closable="false"
    />
    <el-alert
      v-else
      title="Optional audit review"
      description="Confirm the OK result or correct it to NG when evidence shows a missed defect."
      type="info"
      show-icon
      :closable="false"
    />

    <div class="review-panel__form">
      <el-select
        v-model="disposition"
        placeholder="Disposition"
        aria-label="Review disposition"
        style="width: 280px"
      >
        <el-option
          v-for="d in allowed"
          :key="d"
          :value="d"
          :label="DISPOSITION_LABELS[d]"
        />
      </el-select>
      <el-input
        v-model="reviewer"
        placeholder="Reviewer name (required)"
        aria-label="Reviewer name"
        style="width: 220px"
      />
      <el-input
        v-model="reason"
        :placeholder="needsReason ? 'Reason (required for inconclusive)' : 'Reason (optional)'"
        aria-label="Review reason"
        style="width: 320px"
      />
      <el-input
        v-model="note"
        type="textarea"
        :rows="2"
        placeholder="Note (optional)"
        aria-label="Review note"
      />
      <el-button
        type="primary"
        :disabled="!canSubmit"
        :loading="submitting"
        @click="submit"
      >
        Submit review
      </el-button>
    </div>
    <el-alert
      v-if="submitOk"
      title="Review recorded"
      type="success"
      show-icon
      :closable="false"
    />
    <el-alert v-if="submitError" :title="submitError" type="error" show-icon :closable="false" />

    <h4 v-if="reviews.length">Review history (append-only)</h4>
    <ul v-if="reviews.length" class="review-panel__history">
      <li v-for="review in reviews" :key="review.review_id">
        <span class="pill" :class="`pill--${review.disposition === 'CORRECTED_NG' || review.disposition === 'CONFIRMED_NG' ? 'ng' : review.disposition === 'INCONCLUSIVE' ? 'warn' : 'ok'}`">
          {{ review.disposition }}
        </span>
        <span class="review-panel__meta">
          {{ review.reviewer }} · {{ review.created_at }}
        </span>
        <p v-if="review.reason" class="review-panel__reason">{{ review.reason }}</p>
        <p v-if="review.note" class="review-panel__note">{{ review.note }}</p>
      </li>
    </ul>
    <p v-else-if="!loading" class="review-panel__empty">No reviews recorded.</p>
  </section>
</template>

<style scoped>
.review-panel {
  display: flex;
  flex-direction: column;
  gap: 10px;
  padding: 14px;
  border: 1px solid var(--border);
  border-radius: var(--radius);
  background: var(--surface-raised);
  box-shadow: var(--shadow);
}
.review-panel h3 {
  margin: 0;
  font-size: 15px;
}
.review-panel h4 {
  margin: 8px 0 0;
  font-size: 13px;
}
.review-panel__form {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  align-items: flex-start;
}
.review-panel__history {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.review-panel__history li {
  border-left: 2px solid var(--border-strong);
  padding-left: 8px;
}
.review-panel__meta {
  color: var(--text-muted);
  font-size: 12px;
}
.review-panel__reason,
.review-panel__note {
  margin: 2px 0 0;
  font-size: 13px;
}
.review-panel__empty {
  color: var(--text-muted);
  font-size: 13px;
  margin: 0;
}
</style>

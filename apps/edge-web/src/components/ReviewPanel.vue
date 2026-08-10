<script setup lang="ts">
import { onMounted } from "vue";
import type { BusinessResult, InternalDecision, ReviewDisposition } from "@assemblyvision/api-client";
import { useReviewPanel } from "../composables/useReviewPanel";

// Optional human-in-the-loop review panel (docs/design/24-human-in-the-loop.md).
// Reviews are append-only dispositions over immutable evidence; they never
// rewrite the machine decision. The panel is additive: a failure to load or
// submit a review never affects the inspection detail view.

const props = defineProps<{
  inspectionId: string;
  businessResult: BusinessResult;
  internalDecision: InternalDecision;
}>();

const {
  reviews,
  loading,
  historyError,
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
} = useReviewPanel(props.inspectionId, props.businessResult, props.internalDecision);

const DISPOSITION_LABELS: Record<ReviewDisposition, string> = {
  CONFIRMED_NG: "Confirmed NG (defect confirmed)",
  CONFIRMED_OK: "Confirmed OK (false NG corrected)",
  CORRECTED_NG: "Corrected NG (missed defect)",
  INCONCLUSIVE: "Inconclusive (insufficient evidence)",
  REINSPECT: "Reinspect",
};

onMounted(() => {
  void load();
});
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

    <el-alert
      v-if="historyError"
      :title="`Review history could not be loaded: ${historyError}`"
      type="error"
      show-icon
      :closable="false"
    >
      <template #default>
        <p class="review-panel__history-error">
          The existing dispositions are unknown, so a new review would silently supersede them.
          Reload the history before submitting.
        </p>
        <el-button size="small" :loading="loading" @click="load">Reload review history</el-button>
      </template>
    </el-alert>

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
    <p v-else-if="!loading && !historyError" class="review-panel__empty">No reviews recorded.</p>
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
.review-panel__history-error {
  margin: 0 0 8px;
  font-size: 13px;
}
.review-panel__empty {
  color: var(--text-muted);
  font-size: 13px;
  margin: 0;
}
</style>

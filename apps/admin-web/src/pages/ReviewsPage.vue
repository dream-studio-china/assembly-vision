<script setup lang="ts">
import { onMounted, ref } from "vue";
import { useI18n } from "vue-i18n";

import {
  CentralApiError,
  apiClient,
  type Review,
  type ReviewQueuePage,
} from "@assemblyvision/api-client-central";
import { ElMessage } from "element-plus";

import {
  DISPOSITION_LABELS,
  allowedReviewDispositions,
  newIdempotencyKey,
  type ReviewDispositionOption,
} from "../lib/reviews";

const { t } = useI18n();
const page = ref<ReviewQueuePage | null>(null);
const error = ref<string | null>(null);
const submitting = ref(false);

const reviewForm = ref<{
  inspectionId: string;
  disposition: ReviewDispositionOption;
  reason: string;
  allowed: ReviewDispositionOption[];
}>({ inspectionId: "", disposition: "CONFIRMED_NG", reason: "", allowed: [] });
const panelOpen = ref(false);

async function load(cursor?: string): Promise<void> {
  error.value = null;
  try {
    page.value = await apiClient.listReviewQueue(cursor);
  } catch (err) {
    error.value = err instanceof Error ? err.message : t("failed to load the review queue");
  }
}

function openPanel(item: { inspection_id: string; business_result: string; internal_decision: string }): void {
  const allowed = allowedReviewDispositions(item.business_result, item.internal_decision);
  reviewForm.value = {
    inspectionId: item.inspection_id,
    disposition: allowed[0],
    reason: "",
    allowed,
  };
  panelOpen.value = true;
}

async function submit(): Promise<void> {
  submitting.value = true;
  error.value = null;
  try {
    const review: Review = await apiClient.submitReview(
      reviewForm.value.inspectionId,
      {
        disposition: reviewForm.value.disposition,
        reason: reviewForm.value.reason || undefined,
      },
      newIdempotencyKey(),
      0, // first review of an unreviewed queue item
    );
    ElMessage.success(
      t("Review r{revision} recorded ({disposition}).", {
        revision: review.revision,
        disposition: review.disposition,
      }),
    );
    panelOpen.value = false;
    await load();
  } catch (err) {
    if (err instanceof CentralApiError && err.code === "REVIEW_CONFLICT") {
      error.value = t("This inspection was reviewed by someone else; refresh the queue.");
    } else {
      error.value = err instanceof Error ? err.message : t("failed to submit the review");
    }
  } finally {
    submitting.value = false;
  }
}

onMounted(() => load());
</script>

<template>
  <main class="reviews">
    <header>
      <h1>{{ t("Review queue") }}</h1>
      <p class="muted">
        {{
          t(
            "NG and uncertain inspections awaiting append-only review. Machine outcomes are never modified; reviewed labels are shown separately.",
          )
        }}
      </p>
    </header>

    <el-alert v-if="error" :title="error" type="error" show-icon class="block" />

    <el-card class="block">
      <el-table v-if="page" :data="page.items" :empty-text="t('No inspections awaiting review.')">
        <el-table-column prop="completed_at" :label="t('Completed (UTC)')" width="180">
          <template #default="{ row }">{{ new Date(row.completed_at).toLocaleString() }}</template>
        </el-table-column>
        <el-table-column prop="device_id" :label="t('Device')" width="220" />
        <el-table-column prop="product_code" :label="t('Product')" width="120" />
        <el-table-column prop="barcode_value" :label="t('Barcode')" width="130" />
        <el-table-column :label="t('Machine result')" width="120">
          <template #default="{ row }">
            <el-tag type="danger">{{ row.business_result }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column :label="t('Reason codes')">
          <template #default="{ row }">{{ row.reason_codes.join(", ") || "–" }}</template>
        </el-table-column>
        <el-table-column label="" width="110">
          <template #default="{ row }">
            <el-button size="small" type="primary" @click="openPanel(row)">{{ t("Review") }}</el-button>
          </template>
        </el-table-column>
      </el-table>
      <div class="pager">
        <el-button
          v-if="page?.next_cursor"
          type="primary"
          plain
          @click="load(page!.next_cursor ?? undefined)"
        >
          {{ t("Next page") }}
        </el-button>
      </div>
    </el-card>

    <el-dialog v-model="panelOpen" :title="t('Append review')" width="480">
      <p class="muted">
        {{
          t(
            "The original machine decision and evidence remain unchanged; this appends a reviewer disposition (revision 1 of an unreviewed inspection).",
          )
        }}
      </p>
      <el-form label-width="120px">
        <el-form-item :label="t('Disposition')">
          <el-select v-model="reviewForm.disposition" class="full">
            <el-option
              v-for="option in reviewForm.allowed"
              :key="option"
              :label="t(DISPOSITION_LABELS[option])"
              :value="option"
            />
          </el-select>
        </el-form-item>
        <el-form-item :label="t('Reason')">
          <el-input
            v-model="reviewForm.reason"
            type="textarea"
            :rows="3"
            :placeholder="t('Bounded review reason (optional)')"
            maxlength="200"
            show-word-limit
          />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="panelOpen = false">{{ t("Cancel") }}</el-button>
        <el-button type="primary" :loading="submitting" @click="submit">{{ t("Record review") }}</el-button>
      </template>
    </el-dialog>
  </main>
</template>

<style scoped>
.reviews {
  max-width: 1100px;
  margin: 0 auto;
  padding: 1.5rem;
}

.block {
  margin-top: 1rem;
}

.pager {
  margin-top: 1rem;
  text-align: right;
}

.full {
  width: 100%;
}

.muted {
  color: #909399;
}
</style>

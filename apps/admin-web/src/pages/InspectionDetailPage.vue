<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { useRoute } from "vue-router";

import {
  CentralApiError,
  apiClient,
  type InspectionDetail,
  type Review,
} from "@assemblyvision/api-client-central";
import { ElMessage } from "element-plus";

import {
  DISPOSITION_LABELS,
  allowedReviewDispositions,
  newIdempotencyKey,
  type ReviewDispositionOption,
} from "../lib/reviews";

interface InferenceStage {
  model_name: string;
  model_version: string;
  latency_ms: number;
}

interface InferenceMetadata {
  product_detection?: InferenceStage;
  component_detection?: InferenceStage;
}

const route = useRoute();
const detail = ref<InspectionDetail | null>(null);
const error = ref<string | null>(null);
const reviews = ref<Review[]>([]);
const submitting = ref(false);
const metadata = computed<InferenceMetadata | null>(
  () => (detail.value?.inference_metadata as InferenceMetadata | null) ?? null,
);
const latestRevision = computed(() => reviews.value.at(-1)?.revision ?? 0);
const allowedDispositions = computed<ReviewDispositionOption[]>(() =>
  detail.value
    ? allowedReviewDispositions(detail.value.business_result, detail.value.internal_decision)
    : [],
);
const reviewForm = ref<{ disposition: ReviewDispositionOption; reason: string }>({
  disposition: "CONFIRMED_NG",
  reason: "",
});

async function load(): Promise<void> {
  error.value = null;
  try {
    const id = String(route.params.id);
    detail.value = await apiClient.getInspection(id);
    reviews.value = await apiClient.listReviewHistory(id);
    reviewForm.value.disposition = allowedDispositions.value[0] ?? "CONFIRMED_NG";
  } catch (err) {
    error.value = err instanceof Error ? err.message : "failed to load the inspection";
  }
}

async function submitReview(): Promise<void> {
  submitting.value = true;
  error.value = null;
  try {
    await apiClient.submitReview(
      String(route.params.id),
      { disposition: reviewForm.value.disposition, reason: reviewForm.value.reason || undefined },
      newIdempotencyKey(),
      latestRevision.value,
    );
    ElMessage.success("Review recorded.");
    reviewForm.value = {
      disposition: allowedDispositions.value[0] ?? "CONFIRMED_NG",
      reason: "",
    };
    await load();
  } catch (err) {
    if (err instanceof CentralApiError && err.code === "REVIEW_CONFLICT") {
      error.value = "A newer review exists; the page was refreshed.";
      await load();
    } else {
      error.value = err instanceof Error ? err.message : "failed to submit the review";
    }
  } finally {
    submitting.value = false;
  }
}

onMounted(load);
</script>

<template>
  <main class="detail">
    <header>
      <h1>
        Inspection {{ detail?.inspection_id ?? route.params.id }}
        <el-tag v-if="detail?.latest_review" type="warning" class="reviewed-tag">
          reviewed r{{ detail.latest_review.revision }}: {{ detail.latest_review.disposition }}
        </el-tag>
      </h1>
      <p class="muted">Original edge evidence; reviewed labels are shown separately.</p>
    </header>

    <el-alert v-if="error" :title="error" type="error" show-icon class="block" />

    <template v-if="detail">
      <el-card class="block">
        <template #header>Decision</template>
        <el-descriptions :column="3" border>
          <el-descriptions-item label="Result">
            <el-tag :type="detail.business_result === 'OK' ? 'success' : 'danger'">
              {{ detail.business_result }}
            </el-tag>
          </el-descriptions-item>
          <el-descriptions-item label="Internal">
            {{ detail.internal_decision }}
          </el-descriptions-item>
          <el-descriptions-item label="Lifecycle">
            {{ detail.lifecycle_status }}
          </el-descriptions-item>
          <el-descriptions-item label="Product">
            {{ detail.product_code ?? "–" }}
          </el-descriptions-item>
          <el-descriptions-item label="Barcode">
            {{ detail.barcode_value ?? "–" }}
          </el-descriptions-item>
          <el-descriptions-item label="Upload delay">
            {{ detail.upload_delay_ms }} ms
          </el-descriptions-item>
          <el-descriptions-item label="Missing components" :span="3">
            {{ detail.missing_components.join(", ") || "–" }}
          </el-descriptions-item>
          <el-descriptions-item label="Reason codes" :span="3">
            {{ detail.reason_codes.join(", ") || "–" }}
          </el-descriptions-item>
        </el-descriptions>
      </el-card>

      <el-card class="block">
        <template #header>Receipt</template>
        <el-descriptions :column="2" border>
          <el-descriptions-item label="Receipt status">
            <el-tag v-if="detail.receipt_status === 'ACCEPTED'" type="success">
              {{ detail.receipt_status }}
            </el-tag>
            <template v-else>{{ detail.receipt_status ?? "–" }}</template>
          </el-descriptions-item>
          <el-descriptions-item label="Accepted (UTC)">
            {{ detail.receipt_created_at ? new Date(detail.receipt_created_at).toLocaleString() : "–" }}
          </el-descriptions-item>
        </el-descriptions>
      </el-card>

      <el-card class="block">
        <template #header>Component evidence</template>
        <el-table :data="detail.components" empty-text="No component evidence recorded.">
          <el-table-column prop="component_code" label="Component" />
          <el-table-column prop="state" label="State" width="120" />
          <el-table-column label="Best confidence" width="140">
            <template #default="{ row }">
              {{ row.best_confidence == null ? "&ndash;" : row.best_confidence.toFixed(3) }}
            </template>
          </el-table-column>
          <el-table-column prop="detection_count" label="Detections" width="110" />
          <el-table-column prop="usable_frame_count" label="Usable frames" width="120" />
          <el-table-column label="Reasons">
            <template #default="{ row }">{{ row.policy_reason_codes.join(", ") || "&ndash;" }}</template>
          </el-table-column>
        </el-table>
      </el-card>

      <el-card class="block">
        <template #header>Versions and traceability</template>
        <el-descriptions :column="2" border>
          <el-descriptions-item label="Application">
            {{ detail.application_version }}
          </el-descriptions-item>
          <el-descriptions-item label="Rule version">
            {{ detail.rule_version_id }}
          </el-descriptions-item>
          <el-descriptions-item label="Product model">
            {{ detail.product_model_version_id }}
          </el-descriptions-item>
          <el-descriptions-item label="Component model">
            {{ detail.component_model_version_id }}
          </el-descriptions-item>
          <el-descriptions-item label="Aggregation policy">
            {{ detail.aggregation_policy_version }}
          </el-descriptions-item>
          <el-descriptions-item label="Processing">
            {{ detail.processing_ms }} ms
          </el-descriptions-item>
        </el-descriptions>
      </el-card>

      <el-card v-if="metadata" class="block">
        <template #header>Inference traceability</template>
        <el-descriptions :column="2" border>
          <template v-if="metadata.product_detection">
            <el-descriptions-item label="Product model">
              {{ metadata.product_detection.model_name }}
              ({{ metadata.product_detection.model_version }})
            </el-descriptions-item>
            <el-descriptions-item label="Product latency">
              {{ metadata.product_detection.latency_ms }} ms
            </el-descriptions-item>
          </template>
          <template v-if="metadata.component_detection">
            <el-descriptions-item label="Component model">
              {{ metadata.component_detection.model_name }}
              ({{ metadata.component_detection.model_version }})
            </el-descriptions-item>
            <el-descriptions-item label="Component latency">
              {{ metadata.component_detection.latency_ms }} ms
            </el-descriptions-item>
          </template>
        </el-descriptions>
      </el-card>

      <el-card class="block">
        <template #header>Review</template>
        <div v-if="reviews.length === 0" class="muted">No review recorded yet.</div>
        <el-table v-else :data="reviews" empty-text="No review recorded.">
          <el-table-column prop="revision" label="Rev" width="70" />
          <el-table-column prop="disposition" label="Disposition" width="150" />
          <el-table-column prop="reviewer" label="Reviewer" width="140" />
          <el-table-column label="Reason">
            <template #default="{ row }">{{ row.reason ?? "–" }}</template>
          </el-table-column>
          <el-table-column label="Recorded (UTC)" width="180">
            <template #default="{ row }">{{ new Date(row.created_at).toLocaleString() }}</template>
          </el-table-column>
        </el-table>
        <el-divider />
        <p class="muted">
          Appends revision {{ latestRevision + 1 }} with optimistic If-Match; the machine
          decision is never modified.
        </p>
        <div class="review-form">
          <el-select v-model="reviewForm.disposition" class="review-disposition">
            <el-option
              v-for="option in allowedDispositions"
              :key="option"
              :label="DISPOSITION_LABELS[option]"
              :value="option"
            />
          </el-select>
          <el-input
            v-model="reviewForm.reason"
            placeholder="Bounded reason (optional)"
            maxlength="200"
            class="review-reason"
          />
          <el-button type="primary" :loading="submitting" @click="submitReview">
            Append review
          </el-button>
        </div>
      </el-card>

      <el-card class="block">
        <template #header>Media</template>
        <div v-if="detail.media.length === 0" class="muted">No media bound to this inspection.</div>
        <div v-for="item in detail.media" :key="item.source_media_id" class="media">
          <img
            v-if="item.url"
            :src="item.url"
            :alt="`${item.kind} ${item.source_media_id}`"
            class="media-image"
          />
          <div class="media-meta">
            <div>{{ item.kind }} ({{ item.lifecycle }})</div>
            <div class="muted">{{ item.mime_type }} &middot; {{ item.size_bytes }} bytes</div>
          </div>
        </div>
      </el-card>
    </template>
  </main>
</template>

<style scoped>
.detail {
  max-width: 1000px;
  margin: 0 auto;
  padding: 1.5rem;
}

.block {
  margin-top: 1rem;
}

.media {
  display: flex;
  gap: 1rem;
  align-items: flex-start;
  margin: 0.75rem 0;
}

.media-image {
  max-width: 260px;
  border: 1px solid #e4e7ed;
  border-radius: 6px;
}

.media-meta {
  font-size: 0.9rem;
}

.reviewed-tag {
  margin-left: 0.5rem;
  vertical-align: middle;
}

.review-form {
  display: flex;
  gap: 0.75rem;
  align-items: center;
  flex-wrap: wrap;
}

.review-disposition {
  width: 180px;
}

.review-reason {
  flex: 1;
  min-width: 240px;
}

.muted {
  color: #909399;
}
</style>

<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { useRoute } from "vue-router";

import { apiClient, type InspectionDetail } from "@assemblyvision/api-client-central";

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
const metadata = computed<InferenceMetadata | null>(
  () => (detail.value?.inference_metadata as InferenceMetadata | null) ?? null,
);

async function load(): Promise<void> {
  error.value = null;
  try {
    detail.value = await apiClient.getInspection(String(route.params.id));
  } catch (err) {
    error.value = err instanceof Error ? err.message : "failed to load the inspection";
  }
}

onMounted(load);
</script>

<template>
  <main class="detail">
    <header>
      <h1>Inspection {{ detail?.inspection_id ?? route.params.id }}</h1>
      <p class="muted">Original edge evidence; reviewed labels would be shown separately.</p>
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

.muted {
  color: #909399;
}
</style>

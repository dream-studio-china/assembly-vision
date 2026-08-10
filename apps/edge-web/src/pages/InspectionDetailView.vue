<script setup lang="ts">
import type { InspectionRecord, MediaMetadata } from "@assemblyvision/api-client";
import { ApiError } from "@assemblyvision/api-client";
import { DetectionViewer, StatusBadge, formatIsoTime, formatLatency, reasonCodeLabel, toDecisionStatus } from "@assemblyvision/ui";
import type { ViewerBox } from "@assemblyvision/ui";
import { computed, onMounted, ref } from "vue";
import { useRoute } from "vue-router";
import { getApiClient } from "../services/client";
import { placeholderFrame } from "../services/placeholder";

const route = useRoute();
const record = ref<InspectionRecord | null>(null);
const media = ref<MediaMetadata[]>([]);
const error = ref<string | null>(null);
const showProduct = ref(true);
const showRoi = ref(true);

onMounted(async () => {
  const id = String(route.params.id);
  try {
    record.value = await getApiClient().getInspection(id);
    media.value = await getApiClient().listInspectionMedia(id);
  } catch (err) {
    error.value = err instanceof ApiError ? err.message : String(err);
  }
});

const overlayBoxes = computed<ViewerBox[]>(() => {
  const r = record.value;
  if (!r) return [];
  const boxes: ViewerBox[] = [];
  const frameId = r.product_detection?.frame_id ?? "frame";
  if (showProduct.value && r.product_detection) {
    boxes.push({ id: "product", kind: "product", label: "product", box: r.product_detection.bbox, frameId });
  }
  if (showRoi.value && r.roi_result) {
    boxes.push({ id: "roi", kind: "roi", label: "ROI", box: r.roi_result.roi_bbox, frameId });
  }
  return boxes;
});

const sourceSize = computed(() =>
  record.value?.product_detection
    ? { width: record.value.product_detection.bbox.image_width, height: record.value.product_detection.bbox.image_height }
    : { width: 800, height: 600 },
);

const currentFrameId = computed(() => record.value?.product_detection?.frame_id ?? "frame");
const previewSrc = computed(() => placeholderFrame(sourceSize.value.width, sourceSize.value.height));
</script>

<template>
  <div class="detail">
    <el-alert v-if="error" :title="error" type="error" show-icon :closable="false" />

    <template v-else-if="record">
      <div class="detail__head">
        <h2>Inspection {{ record.inspection_id }}</h2>
        <StatusBadge :status="toDecisionStatus(record.decision.business_result, record.decision.internal_decision)" />
      </div>

      <div class="detail__grid">
        <section class="detail__panel">
          <h3>Evidence</h3>
          <div class="detail__viewer">
            <DetectionViewer
              :image-url="previewSrc"
              :image-width="sourceSize.width"
              :image-height="sourceSize.height"
              :boxes="overlayBoxes"
              :current-frame-id="currentFrameId"
            />
            <el-checkbox v-model="showProduct" label="Product box" />
            <el-checkbox v-model="showRoi" label="ROI" />
          </div>

          <h3>Reason codes</h3>
          <ul class="detail__reasons">
            <li v-for="code in record.decision.reason_codes" :key="code">{{ reasonCodeLabel(code) }}</li>
            <li v-if="!record.decision.reason_codes.length">None</li>
          </ul>

          <h3>Components</h3>
          <el-table :data="record.evidence" size="small">
            <el-table-column prop="component_code" label="Component" />
            <el-table-column prop="state" label="State" width="100">
              <template #default="{ row }">
                <span class="pill" :class="`pill--${row.state.toLowerCase()}`">{{ row.state }}</span>
              </template>
            </el-table-column>
            <el-table-column prop="best_confidence" label="Confidence" width="100">
              <template #default="{ row }">{{ row.best_confidence?.toFixed(2) ?? "-" }}</template>
            </el-table-column>
            <el-table-column prop="detection_count" label="Detections" width="100" />
          </el-table>
        </section>

        <aside class="detail__side">
          <h3>Identity</h3>
          <dl class="detail__dl">
            <dt>Completed</dt>
            <dd>{{ formatIsoTime(record.completed_at) }}</dd>
            <dt>Product</dt>
            <dd>{{ record.product_resolution.product_code ?? "-" }}</dd>
            <dt>Latency</dt>
            <dd>{{ formatLatency(record.processing_ms) }}</dd>
            <dt>Upload</dt>
            <dd>{{ record.synchronization_status }}</dd>
          </dl>

          <h3>Versions</h3>
          <dl class="detail__dl">
            <dt>App</dt>
            <dd>{{ record.application_version }}</dd>
            <dt>Product model</dt>
            <dd>{{ record.product_model_version_id }}</dd>
            <dt>Component model</dt>
            <dd>{{ record.component_model_version_id }}</dd>
            <dt>Rule</dt>
            <dd>{{ record.rule_version_id }}</dd>
          </dl>

          <h3>Media</h3>
          <ul class="detail__media">
            <li v-for="m in media" :key="m.media_id">
              {{ m.kind }} · {{ (m.size_bytes / 1024).toFixed(1) }} KB
              <span v-if="m.lifecycle === 'PURGED'" class="pill pill--warn">purged</span>
            </li>
            <li v-if="!media.length">No media</li>
          </ul>
        </aside>
      </div>
    </template>

    <el-empty v-else description="Loading" />
  </div>
</template>

<style scoped>
.detail {
  padding: 16px;
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.detail__head {
  display: flex;
  align-items: center;
  gap: 16px;
}
.detail__head h2 {
  margin: 0;
  font-size: 18px;
}
.detail__grid {
  display: grid;
  grid-template-columns: 1fr 320px;
  gap: 16px;
}
.detail__panel {
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.detail__viewer {
  height: 50vh;
  min-height: 280px;
  border: 1px solid var(--border);
  border-radius: var(--radius);
  background: var(--surface-raised);
  box-shadow: var(--shadow);
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding: 8px;
}
.detail__viewer .detection-viewer {
  flex: 1;
}
.detail__reasons {
  margin: 0;
  padding-left: 20px;
}
.detail__dl {
  display: grid;
  grid-template-columns: auto 1fr;
  gap: 4px 12px;
  font-size: 13px;
}
.detail__dl dt {
  color: var(--text-muted);
  word-break: break-word;
}
.detail__dl dd {
  margin: 0;
  word-break: break-all;
}
.detail__media {
  margin: 0;
  padding: 0;
  list-style: none;
  font-size: 13px;
}
.pill {
  display: inline-block;
  border-radius: var(--radius-small);
  padding: 1px 10px;
  font-size: 12px;
}
.pill--present {
  background: var(--status-ok-soft);
  color: var(--status-ok);
}
.pill--missing {
  background: var(--status-ng-soft);
  color: var(--status-ng);
}
.pill--uncertain {
  background: var(--status-warning-soft);
  color: var(--status-warning);
}
.pill--warn {
  background: var(--status-warning-soft);
  color: var(--status-warning);
}
</style>

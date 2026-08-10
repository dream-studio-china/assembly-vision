<script setup lang="ts">
// Production inspection dashboard: the main operator workflow
// (status, product image, rules, actions).

import type { InspectionImages } from "@assemblyvision/api-client";
import { DetectionViewer, StatusBadge, formatIsoTime, formatLatency } from "@assemblyvision/ui";
import type { ViewerBox } from "@assemblyvision/ui";
import { ElMessage } from "element-plus";
import { computed, onMounted, ref } from "vue";
import { useInspectionStore } from "../stores/inspection";
import { isMockMode } from "../services/client";
import { inspectionService } from "../services/inspectionService";
import { mockCameraFrame } from "../mock/images";

const store = useInspectionStore();

// The operator workflow (current inspection, confirm, continue, manual) is a
// deterministic mock demonstration and must never be shown alongside live
// device state (F6, ADR-012). In real mode the dashboard explains that and the
// read-only views display the actual inspection data.
const operatorWorkflow = isMockMode();

const images = ref<InspectionImages | null>(null);
const fallback = mockCameraFrame(800, 600);

const statusLabel = computed(() => store.current?.status ?? "WAITING");

// Map the operator workflow state onto the color-independent StatusBadge.
const badgeStatus = computed(() => {
  const s = statusLabel.value;
  if (s === "PASS") return "OK";
  if (s === "NG") return "NG";
  if (s === "PROCESSING") return "UNCERTAIN";
  return "UNCERTAIN";
});

const isBusy = computed(() => store.loading);

// Detection regions over the current product image in source coordinates.
const currentFrameId = computed(() => store.current?.inspection_id ?? "frame");
const overlayBoxes = computed<ViewerBox[]>(() => {
  const id = store.current?.inspection_id ?? "frame";
  const status = store.current?.status;
  const boxes: ViewerBox[] = [];
  if (status === "NG") {
    boxes.push({
      id: "manual",
      kind: "component",
      label: "manual (missing)",
      box: { x_min: 500, y_min: 420, x_max: 620, y_max: 480 },
      frameId: id,
    });
  } else if (status === "PASS" || status === "PROCESSING") {
    boxes.push({
      id: "product",
      kind: "product",
      label: "product",
      box: { x_min: 120, y_min: 90, x_max: 680, y_max: 520 },
      frameId: id,
    });
  }
  boxes.push({
    id: "roi",
    kind: "roi",
    label: "ROI",
    box: { x_min: 80, y_min: 60, x_max: 720, y_max: 550 },
    frameId: id,
  });
  return boxes;
});

async function loadImages(): Promise<void> {
  const id = store.current?.inspection_id;
  if (!id) {
    images.value = null;
    return;
  }
  try {
    images.value = await inspectionService.getImages(id);
  } catch {
    images.value = null;
  }
}

async function confirm(): Promise<void> {
  await store.confirmResult();
  if (store.error) ElMessage.error(store.error);
  await loadImages();
}

async function next(): Promise<void> {
  await store.continueNext();
  if (store.error) ElMessage.error(store.error);
  await loadImages();
}

async function manual(): Promise<void> {
  await store.triggerManual();
  if (store.error) ElMessage.error(store.error);
  await loadImages();
}

onMounted(async () => {
  if (!operatorWorkflow) return;
  await store.loadCurrent();
  await loadImages();
});
</script>

<template>
  <div class="dashboard">
    <template v-if="operatorWorkflow">
      <div class="dashboard__top">
      <section class="panel">
        <h2 class="dashboard__panel-title">Current product image</h2>
        <div class="dashboard__image">
          <DetectionViewer
            :image-url="images?.detection ?? fallback"
            :image-width="800"
            :image-height="600"
            :boxes="overlayBoxes"
            :current-frame-id="currentFrameId"
          />
        </div>
      </section>

      <section class="dashboard__status panel">
        <div class="dashboard__status-row">
          <span class="dashboard__label">Current status</span>
          <StatusBadge :status="badgeStatus" />
          <span class="dashboard__raw-status">{{ statusLabel }}</span>
        </div>
        <div class="dashboard__meta">
          <dl>
            <dt>Product SN</dt>
            <dd>{{ store.current?.sn ?? "—" }}</dd>
            <dt>Product</dt>
            <dd>{{ store.current?.product_code || "—" }}</dd>
            <dt>Inspection time</dt>
            <dd>{{ formatIsoTime(store.current?.started_at) }}</dd>
            <dt>Duration</dt>
            <dd>{{ formatLatency(store.current?.duration_ms) }}</dd>
            <dt>Operator</dt>
            <dd>{{ store.current?.operator ?? "—" }}</dd>
          </dl>
        </div>
        <div class="dashboard__progress">
          <el-progress
            :percentage="Math.round((store.current?.progress ?? 0) * 100)"
            :stroke-width="12"
          />
        </div>
      </section>
    </div>

    <section class="panel">
      <h2>Inspection rules</h2>
      <el-table :data="store.current?.rules ?? []" size="large" v-loading="store.loading">
        <el-table-column prop="name" label="Rule" min-width="220" />
        <el-table-column label="Status" width="130">
          <template #default="{ row }">
            <span class="rule" :class="`rule--${row.status.toLowerCase()}`">{{ row.status }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="result_message" label="Result message" min-width="260" />
      </el-table>
    </section>

    <section class="panel dashboard__actions">
      <el-button
        type="success"
        size="large"
        :disabled="statusLabel !== 'PROCESSING' || isBusy"
        :loading="isBusy"
        @click="confirm"
      >
        Confirm result
      </el-button>
      <el-button type="primary" size="large" :loading="isBusy" @click="next">
        Continue next inspection
      </el-button>
      <el-button size="large" :loading="isBusy" @click="manual">
        Trigger manual inspection
      </el-button>
    </section>
    </template>

    <section v-else class="panel dashboard__real-mode">
      <h2>Operator workflow is a mock demonstration</h2>
      <p>
        The confirm / continue / manual actions and the current-inspection
        status are deterministic mock data and are hidden while the dashboard is
        connected to the live read-only API (ADR-012). Use
        <router-link to="/history">History</router-link>,
        <router-link to="/live">Live inspection</router-link>, and
        <router-link to="/statistics">Statistics</router-link> for real data.
      </p>
    </section>
  </div>
</template>

<style scoped>
.dashboard {
  display: flex;
  flex-direction: column;
  gap: 16px;
}
.dashboard__top {
  display: grid;
  grid-template-columns: 1fr 340px;
  gap: 16px;
}
.dashboard__panel-title {
  margin: 0 0 10px;
  font-size: 14px;
  color: var(--text-muted);
}
.dashboard__image {
  height: 52vh;
  min-height: 300px;
  border: 1px solid var(--border);
  border-radius: var(--radius-small);
}
.panel {
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: var(--panel-padding);
  background: var(--surface-raised);
  box-shadow: var(--shadow);
}
.dashboard__status-row {
  display: flex;
  align-items: center;
  gap: 12px;
}
.dashboard__label {
  font-weight: 600;
  color: var(--text);
}
.dashboard__raw-status {
  font-size: 13px;
  color: var(--text-muted);
}
.dashboard__meta dl {
  display: grid;
  grid-template-columns: 130px 1fr;
  gap: 6px 16px;
  font-size: 14px;
  margin: 12px 0;
}
.dashboard__meta dt {
  color: var(--text-muted);
}
.dashboard__meta dd {
  margin: 0;
  font-variant-numeric: tabular-nums;
}
.dashboard__progress {
  margin-top: 8px;
}
.dashboard__actions {
  display: flex;
  gap: 12px;
}
.dashboard__real-mode h2 {
  margin: 0 0 8px;
  font-size: 16px;
  color: var(--text);
}
.dashboard__real-mode p {
  margin: 0;
  font-size: 14px;
  color: var(--text-muted);
}
.rule {
  display: inline-block;
  border-radius: var(--radius-small);
  padding: 2px 12px;
  font-size: 12px;
}
.rule--pass {
  background: var(--status-ok-soft);
  color: var(--status-ok);
}
.rule--ng {
  background: var(--status-ng-soft);
  color: var(--status-ng);
}
.rule--checking {
  background: var(--status-warning-soft);
  color: var(--status-warning);
}
.rule--pending {
  background: var(--surface-muted);
  color: var(--text-muted);
}
</style>

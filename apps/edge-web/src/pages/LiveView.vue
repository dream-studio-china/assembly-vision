<script setup lang="ts">
// Live inspection screen (docs/design/16-edge-dashboard.md 16.4).

import { DetectionViewer, StatusBadge, toDecisionStatus, formatIsoTime, formatLatency, reasonCodeLabel } from "@assemblyvision/ui";
import type { ViewerBox } from "@assemblyvision/ui";
import type { InspectionRecord, InspectionSummary } from "@assemblyvision/api-client";
import { computed, onBeforeUnmount, onMounted, ref } from "vue";
import { useAlertsStore } from "../stores/alerts";
import { useRuntimeStore } from "../stores/runtime";
import { getApiClient } from "../services/client";
import { placeholderFrame } from "../services/placeholder";

const runtime = useRuntimeStore();
const alerts = useAlertsStore();

const previewSrc = computed(() => placeholderFrame(sourceSize.value.width, sourceSize.value.height));

const recent = ref<InspectionSummary[]>([]);
const latestRecord = ref<InspectionRecord | null>(null);
const loadingRecent = ref(false);
let pollTimer: ReturnType<typeof setInterval> | null = null;

const latest = computed(() => {
  const ok = recent.value.find((r) => r.business_result === "OK");
  const ng = recent.value.find((r) => r.business_result === "NG");
  return ng ?? ok ?? null;
});

const decisionStatus = computed(() =>
  latest.value
    ? toDecisionStatus(latest.value.business_result, latest.value.internal_decision)
    : "OK",
);

const sourceSize = computed(() => ({
  width: runtime.camera?.source_width ?? 800,
  height: runtime.camera?.source_height ?? 600,
}));

// Overlay boxes in source coordinates from the latest inspection. Component
// boxes are not persisted in the aggregated record, so only product and ROI
// are drawn (design 16.4.1 shows exactly these reserved layers).
const overlayBoxes = computed<ViewerBox[]>(() => {
  const record = latestRecord.value;
  if (!record) return [];
  const boxes: ViewerBox[] = [];
  if (record.product_detection) {
    boxes.push({ id: "product", kind: "product", label: "product", box: record.product_detection.bbox, frameId: record.product_detection.frame_id });
  }
  if (record.roi_result) {
    boxes.push({ id: "roi", kind: "roi", label: "ROI", box: record.roi_result.roi_bbox, frameId: record.roi_result.frame_id });
  }
  return boxes;
});

const currentFrameId = computed<string | null>(() => latestRecord.value?.product_detection?.frame_id ?? null);
const lastFrameAt = computed(() => (latestRecord.value ? latestRecord.value.completed_at : null));

async function loadRecent(): Promise<void> {
  loadingRecent.value = true;
  try {
    const page = await getApiClient().listInspections({ limit: 10 });
    recent.value = page.items;
    const first = page.items[0];
    if (first) {
      latestRecord.value = await getApiClient().getInspection(first.inspection_id);
    } else {
      latestRecord.value = null;
    }
  } finally {
    loadingRecent.value = false;
  }
}

onMounted(() => {
  void loadRecent();
  pollTimer = setInterval(() => {
    void runtime.refresh();
    void loadRecent();
  }, 5000);
  void runtime.refresh().then(() => {
    if (runtime.status) {
      alerts.setFromStatus(
        runtime.status.inspection_ready,
        runtime.status.camera_connected,
        runtime.status.central_connected,
        runtime.status.disk_free_bytes,
      );
    }
  });
});

onBeforeUnmount(() => {
  if (pollTimer !== null) clearInterval(pollTimer);
});
</script>

<template>
  <div class="live">
    <div class="live__main">
      <section class="live__viewer">
        <DetectionViewer
          :image-url="previewSrc"
          :image-width="sourceSize.width"
          :image-height="sourceSize.height"
          :boxes="overlayBoxes"
          :current-frame-id="currentFrameId"
          :last-frame-at="lastFrameAt"
        />
      </section>

      <aside class="live__decision">
        <h2>Latest result</h2>
        <template v-if="latest">
          <StatusBadge :status="decisionStatus" />
          <dl class="live__meta">
            <dt>Inspection</dt>
            <dd>{{ latest.inspection_id }}</dd>
            <dt>Completed</dt>
            <dd>{{ formatIsoTime(latest.completed_at) }}</dd>
            <dt>Latency</dt>
            <dd>{{ formatLatency(latest.latency_ms) }}</dd>
            <dt>Reasons</dt>
            <dd>
              <span v-for="code in latest.reason_summary" :key="code" class="live__reason">
                {{ reasonCodeLabel(code) }}
              </span>
              <span v-if="!latest.reason_summary.length">-</span>
            </dd>
          </dl>
        </template>
        <el-empty v-else description="No results yet" :image-size="60" />
      </aside>
    </div>

    <div class="live__strips">
      <div class="strip">
        <h3>Readiness</h3>
        <ul>
          <li><span class="pill" :class="runtime.status?.inspection_ready ? 'pill--ok' : 'pill--ng'">Inspection engine</span></li>
          <li><span class="pill" :class="runtime.status?.camera_connected ? 'pill--ok' : 'pill--ng'">Camera</span></li>
          <li><span class="pill" :class="runtime.status?.model_loaded ? 'pill--ok' : 'pill--ng'">Model</span></li>
          <li><span class="pill" :class="runtime.status && runtime.status.disk_free_bytes > 5e9 ? 'pill--ok' : 'pill--ng'">Disk</span></li>
        </ul>
      </div>
      <div class="strip">
        <h3>Connectivity</h3>
        <ul>
          <li><span class="pill" :class="runtime.status?.central_connected ? 'pill--ok' : 'pill--warn'">Central</span></li>
          <li>Uploads pending: {{ runtime.status?.upload_pending_count ?? "-" }}</li>
          <li>Sync: {{ runtime.status?.sync_ready ? "ready" : "not ready" }}</li>
        </ul>
      </div>
      <div v-if="alerts.alerts.length" class="strip strip--alerts">
        <h3>Alerts</h3>
        <ul>
          <li v-for="alert in alerts.alerts" :key="alert.id">
            <span class="pill" :class="alert.severity === 'critical' ? 'pill--ng' : 'pill--warn'">
              {{ alert.message }}
            </span>
          </li>
        </ul>
      </div>
    </div>

    <section class="live__rail">
      <h3>Recent inspections</h3>
      <el-table :data="recent" v-loading="loadingRecent" size="small">
        <el-table-column prop="inspection_id" label="Inspection ID" min-width="180" />
        <el-table-column label="Result" width="110">
          <template #default="{ row }">
            <StatusBadge :status="toDecisionStatus(row.business_result, row.internal_decision)" />
          </template>
        </el-table-column>
        <el-table-column prop="completed_at" label="Completed" min-width="170">
          <template #default="{ row }">{{ formatIsoTime(row.completed_at) }}</template>
        </el-table-column>
        <el-table-column label="" width="70">
          <template #default="{ row }">
            <router-link :to="`/inspections/${row.inspection_id}`">detail</router-link>
          </template>
        </el-table-column>
      </el-table>
    </section>
  </div>
</template>

<style scoped>
.live {
  display: flex;
  flex-direction: column;
  gap: 16px;
  padding: 16px;
}
.live__main {
  display: grid;
  grid-template-columns: 1fr 320px;
  gap: 16px;
}
.live__viewer {
  height: 60vh;
  min-height: 320px;
  border: 1px solid #e0e0e0;
  border-radius: 6px;
}
.live__decision {
  border: 1px solid #e0e0e0;
  border-radius: 6px;
  padding: 16px;
}
.live__meta {
  display: grid;
  grid-template-columns: auto 1fr;
  gap: 4px 12px;
  font-size: 13px;
  margin-top: 12px;
}
.live__meta dt {
  color: #6b7280;
}
.live__reason {
  background: #fdecea;
  color: #b71c1c;
  border-radius: 3px;
  padding: 1px 6px;
  margin-right: 4px;
  font-size: 12px;
}
.live__strips {
  display: flex;
  gap: 16px;
  flex-wrap: wrap;
}
.strip {
  border: 1px solid #e0e0e0;
  border-radius: 6px;
  padding: 8px 12px;
  flex: 1;
  min-width: 220px;
}
.strip h3 {
  margin: 0 0 8px;
  font-size: 13px;
  color: #6b7280;
}
.strip ul {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 6px;
  font-size: 13px;
}
.pill {
  display: inline-block;
  border-radius: 999px;
  padding: 1px 10px;
  font-size: 12px;
}
.pill--ok {
  background: #e8f5e9;
  color: #1b5e20;
}
.pill--ng {
  background: #fdecea;
  color: #b71c1c;
}
.pill--warn {
  background: #fff3e0;
  color: #e65100;
}
.live__rail {
  border: 1px solid #e0e0e0;
  border-radius: 6px;
  padding: 12px;
}
</style>

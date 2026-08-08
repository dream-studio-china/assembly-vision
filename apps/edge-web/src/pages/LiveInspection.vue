<script setup lang="ts">
// Live inspection view: camera feed, detection result, detection region
// overlay, inspection progress, and detailed inspection info + runtime logs
// (docs/design/16-edge-dashboard.md 16.4).

import type { InspectionImages, LogEvent } from "@assemblyvision/api-client";
import { DetectionViewer, StatusBadge, formatBytes, formatIsoTime, formatLatency } from "@assemblyvision/ui";
import type { ViewerBox } from "@assemblyvision/ui";
import { computed, onBeforeUnmount, onMounted, ref } from "vue";
import { mockCameraFrame } from "../mock/images";
import { useInspectionStore } from "../stores/inspection";
import { useRuntimeStore } from "../stores/runtime";
import { isMockMode } from "../services/client";
import { inspectionService } from "../services/inspectionService";

const store = useInspectionStore();
const runtime = useRuntimeStore();
const images = ref<InspectionImages | null>(null);
const logs = ref<LogEvent[]>([]);
let timer: ReturnType<typeof setInterval> | null = null;

// In real mode there is no live operator window (M1, ADR-012), so simulated
// frames and the mock current inspection must never be shown alongside live
// device state (F6). Media that is absent or unreachable renders as an explicit
// unavailable state instead of a fabricated frame.
const isMock = isMockMode();
const cameraFrame = computed(() => (isMock ? mockCameraFrame(800, 600) : null));
const detectionUrl = computed(() => images.value?.detection || cameraFrame.value || null);
const annotatedUrl = computed(() => images.value?.annotated || cameraFrame.value || null);

const badgeStatus = computed(() => {
  const s = store.current?.status ?? "WAITING";
  if (s === "PASS") return "OK";
  if (s === "NG") return "NG";
  return "UNCERTAIN";
});

const currentFrameId = computed(() => (store.current?.inspection_id ?? "frame") as string);

// Detection regions drawn over the detection image in source coordinates.
const detectionBoxes = computed<ViewerBox[]>(() => {
  const id = store.current?.inspection_id ?? "frame";
  const boxes: ViewerBox[] = [];
  if (store.current?.status === "NG") {
    boxes.push({ id: "manual", kind: "component", label: "manual (missing)", box: { x_min: 500, y_min: 420, x_max: 620, y_max: 480 }, frameId: id });
  } else if (store.current?.status === "PASS" || store.current?.status === "PROCESSING") {
    boxes.push({ id: "product", kind: "product", label: "product", box: { x_min: 120, y_min: 90, x_max: 680, y_max: 520 }, frameId: id });
  }
  boxes.push({ id: "roi", kind: "roi", label: "ROI", box: { x_min: 80, y_min: 60, x_max: 720, y_max: 550 }, frameId: id });
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

async function loadLogs(): Promise<void> {
  try {
    logs.value = (await inspectionService.listLogs()).items;
  } catch {
    // keep the last known log set
  }
}

async function refresh(): Promise<void> {
  if (isMock) await store.loadCurrent();
  await runtime.refresh();
  await Promise.all([loadImages(), loadLogs()]);
}

onMounted(() => {
  void refresh();
  timer = setInterval(() => void refresh(), 5000);
});

onBeforeUnmount(() => {
  if (timer !== null) clearInterval(timer);
});
</script>

<template>
  <div class="live-inspection">
    <div class="live-inspection__head">
      <div>
        <p class="live-inspection__eyebrow">LOCAL INSPECTION</p>
        <h2>Live inspection</h2>
      </div>
      <StatusBadge :status="badgeStatus" />
      <span class="live-inspection__sn">{{ store.current?.sn ?? "waiting" }}</span>
      <span class="live-inspection__inspection-id">{{ store.current?.inspection_id }}</span>
    </div>

    <div class="live-inspection__progress">
      <el-progress
        :percentage="Math.round((store.current?.progress ?? 0) * 100)"
        :stroke-width="10"
      />
    </div>

    <div class="live-inspection__strips" aria-label="Inspection readiness and connectivity">
      <section class="status-strip">
        <h3>Inspection readiness</h3>
        <div class="status-strip__items">
          <span class="status-chip" :class="runtime.status?.inspection_ready ? 'status-chip--ready' : 'status-chip--critical'">Engine {{ runtime.status?.inspection_ready ? "ready" : "not ready" }}</span>
          <span class="status-chip" :class="runtime.status?.camera_connected ? 'status-chip--ready' : 'status-chip--critical'">Camera {{ runtime.status?.camera_connected ? "connected" : "offline" }}</span>
          <span class="status-chip" :class="runtime.status?.model_loaded ? 'status-chip--ready' : 'status-chip--critical'">Model {{ runtime.status?.model_loaded ? "loaded" : "unavailable" }}</span>
          <span class="status-chip" :class="(runtime.status?.disk_free_bytes ?? 0) >= 5 * 1024 ** 3 ? 'status-chip--ready' : 'status-chip--warning'">Disk {{ runtime.status ? formatBytes(runtime.status.disk_free_bytes) + " free" : "unknown" }}</span>
        </div>
      </section>
      <section class="status-strip">
        <h3>Connectivity</h3>
        <div class="status-strip__items">
          <span class="status-chip status-chip--ready">Local API available</span>
          <span class="status-chip" :class="runtime.status?.central_connected ? 'status-chip--ready' : 'status-chip--warning'">Central {{ runtime.status?.central_connected ? "connected" : "offline" }}</span>
          <span class="status-chip status-chip--neutral">Uploads pending {{ runtime.status?.upload_pending_count ?? "-" }}</span>
        </div>
      </section>
    </div>

    <div class="live-inspection__grid">
      <section class="panel">
        <h3>Camera image</h3>
        <div class="live-inspection__frame">
          <img v-if="cameraFrame" :src="cameraFrame" alt="camera preview" />
          <el-empty
            v-else
            description="No camera feed in read-only mode"
            :image-size="72"
            class="live-inspection__unavailable"
          />
        </div>
      </section>

      <section class="panel">
        <h3>Detection result</h3>
        <div class="live-inspection__viewer">
          <DetectionViewer
            v-if="detectionUrl"
            :image-url="detectionUrl"
            :image-width="800"
            :image-height="600"
            :boxes="detectionBoxes"
            :current-frame-id="currentFrameId"
          />
          <el-empty
            v-else
            description="No detection image available"
            :image-size="72"
            class="live-inspection__unavailable"
          />
        </div>
      </section>

      <section class="panel">
        <h3>Detection regions</h3>
        <div class="live-inspection__viewer">
          <DetectionViewer
            v-if="annotatedUrl"
            :image-url="annotatedUrl"
            :image-width="800"
            :image-height="600"
            :boxes="detectionBoxes"
            :current-frame-id="currentFrameId"
          />
          <el-empty
            v-else
            description="No annotated image available"
            :image-size="72"
            class="live-inspection__unavailable"
          />
        </div>
      </section>
    </div>

    <div class="live-inspection__info">
      <section class="panel">
        <h3>Inspection details</h3>
        <dl class="info-dl">
          <dt>Inspection ID</dt>
          <dd>{{ store.current?.inspection_id }}</dd>
          <dt>SN</dt>
          <dd>{{ store.current?.sn ?? "—" }}</dd>
          <dt>Product</dt>
          <dd>{{ store.current?.product_code || "—" }}</dd>
          <dt>Operator</dt>
          <dd>{{ store.current?.operator ?? "—" }}</dd>
          <dt>Started</dt>
          <dd>{{ formatIsoTime(store.current?.started_at) }}</dd>
          <dt>Duration</dt>
          <dd>{{ formatLatency(store.current?.duration_ms) }}</dd>
          <dt>Status</dt>
          <dd>{{ store.current?.status ?? "WAITING" }}</dd>
        </dl>
      </section>

      <section class="panel">
        <h3>Rules</h3>
        <el-table :data="store.current?.rules ?? []" size="small">
          <el-table-column prop="name" label="Rule" min-width="150" />
          <el-table-column label="Status" width="100">
            <template #default="{ row }">
              <span class="rule" :class="`rule--${row.status.toLowerCase()}`">{{ row.status }}</span>
            </template>
          </el-table-column>
          <el-table-column prop="result_message" label="Result message" min-width="160" />
        </el-table>
      </section>
    </div>

    <section class="panel live-inspection__logs">
      <h3>Runtime logs</h3>
      <el-table :data="logs" size="small" height="280">
        <el-table-column label="Time" width="150">
          <template #default="{ row }">{{ formatIsoTime(row.logged_at) }}</template>
        </el-table-column>
        <el-table-column prop="level" label="Level" width="70" />
        <el-table-column prop="component" label="Component" width="140" />
        <el-table-column prop="message" label="Message" min-width="200" />
      </el-table>
    </section>
  </div>
</template>

<style scoped>
.live-inspection {
  display: flex;
  flex-direction: column;
  gap: 16px;
}
.live-inspection__head {
  display: flex;
  align-items: center;
  gap: 14px;
  flex-wrap: wrap;
}
.live-inspection__head h2 {
  margin: 0;
  color: #17202a;
  font-size: 24px;
}
.live-inspection__eyebrow { margin: 0 0 3px; color: #176b87; font-size: 11px; font-weight: 800; letter-spacing: 0.1em; }
.live-inspection__sn {
  color: #6b7280;
  font-size: 14px;
}
.live-inspection__inspection-id {
  color: #9aa2ae;
  font-size: 12px;
}
.live-inspection__strips { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px; }
.status-strip { border: 1px solid #cbd7dc; border-left: 4px solid #176b87; border-radius: 6px; background: #fff; padding: 11px 12px; }
.status-strip h3 { margin: 0 0 8px; color: #46555c; font-size: 12px; letter-spacing: 0.03em; text-transform: uppercase; }
.status-strip__items { display: flex; flex-wrap: wrap; gap: 7px; }
.status-chip { border-radius: 3px; padding: 4px 7px; font-size: 12px; font-weight: 650; }
.status-chip--ready { background: #e5f3ed; color: #17633c; }
.status-chip--critical { background: #fde7e4; color: #a72d24; }
.status-chip--warning { background: #fff1d8; color: #825600; }
.status-chip--neutral { background: #e9eef0; color: #405159; }
.live-inspection__grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 16px;
}
.live-inspection__info {
  display: grid;
  grid-template-columns: 1fr 1.4fr;
  gap: 16px;
}
.live-inspection__logs {
  width: 100%;
}
.live-inspection__frame img {
  width: 100%;
  display: block;
  border-radius: 4px;
}
.live-inspection__viewer {
  height: 46vh;
  min-height: 280px;
  border: 1px solid #e0e0e0;
  border-radius: 6px;
}
.live-inspection__unavailable {
  height: 100%;
  min-height: 280px;
  display: flex;
  align-items: center;
  justify-content: center;
}
.panel {
  border: 1px solid #cbd7dc;
  border-radius: 6px;
  padding: 14px;
  background: #fff;
}
.panel h3 {
  margin: 0 0 10px;
  font-size: 14px;
  color: #374151;
}
.info-dl {
  display: grid;
  grid-template-columns: 110px 1fr;
  gap: 6px 12px;
  font-size: 13px;
  margin: 0;
}
.info-dl dt {
  color: #6b7280;
}
.info-dl dd {
  margin: 0;
  word-break: break-all;
}
.rule {
  display: inline-block;
  border-radius: 999px;
  padding: 1px 10px;
  font-size: 12px;
}
.rule--pass {
  background: #e8f5e9;
  color: #1b5e20;
}
.rule--ng {
  background: #fdecea;
  color: #b71c1c;
}
.rule--checking {
  background: #fff3e0;
  color: #e65100;
}
.rule--pending {
  background: #eceff1;
  color: #546e7a;
}
@media (max-width: 1180px) {
  .live-inspection__grid { grid-template-columns: repeat(2, 1fr); }
  .live-inspection__grid > :last-child { grid-column: span 2; }
}
@media (max-width: 760px) {
  .live-inspection__strips, .live-inspection__grid, .live-inspection__info { grid-template-columns: 1fr; }
  .live-inspection__grid > :last-child { grid-column: auto; }
  .live-inspection__viewer { height: 42vh; min-height: 220px; }
}
</style>

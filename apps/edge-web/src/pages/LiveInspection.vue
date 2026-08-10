<script setup lang="ts">
// Live inspection view: camera feed, detection result, detection region
// overlay, inspection progress, and detailed inspection info + runtime logs
// (docs/design/16-edge-dashboard.md 16.4).

import type { InspectionImages, LogEvent, WSEventEnvelope } from "@assemblyvision/api-client";
import { DetectionViewer, StatusBadge, formatBytes, formatIsoTime, formatLatency } from "@assemblyvision/ui";
import type { ViewerBox } from "@assemblyvision/ui";
import { ReconnectingWebSocket } from "@assemblyvision/api-client";
import { computed, onBeforeUnmount, onMounted, ref } from "vue";
import { mockCameraFrame } from "../mock/images";
import { useInspectionStore } from "../stores/inspection";
import { useRuntimeStore } from "../stores/runtime";
import {
  getRuntimeWsUrl,
  isCrossOriginHttp,
  isMockMode,
  requestRuntimeTicket,
} from "../services/client";
import { inspectionService } from "../services/inspectionService";

const store = useInspectionStore();
const runtime = useRuntimeStore();
const images = ref<InspectionImages | null>(null);
const logs = ref<LogEvent[]>([]);
let timer: ReturnType<typeof setInterval> | null = null;
let socket: ReconnectingWebSocket | null = null;

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

function onRuntimeEvent(event: WSEventEnvelope): void {
  // REST remains the source of truth: an event only prompts a snapshot
  // refresh (E4a, design 16 rule 3). Ignore unknown future event types.
  if (
    event.type === "inspection.started" ||
    event.type === "inspection.completed" ||
    event.type === "device.status_changed" ||
    event.type === "upload.changed"
  ) {
    void refresh();
  }
}

function runtimeWsUrl(): string {
  return getRuntimeWsUrl();
}

onMounted(() => {
  void refresh();
  // Slow fallback poll; the WebSocket channel drives timely refreshes.
  timer = setInterval(() => void refresh(), 30000);
  if (!isMock) {
    socket = new ReconnectingWebSocket();
    socket.onGap(() => void refresh());
    socket.subscribe(onRuntimeEvent);
    // Cross-origin browser sockets cannot set an Authorization header or use
    // the same-origin session cookie, so exchange the viewer credential for a
    // one-time ticket sent as the subprotocol; the provider is re-invoked on
    // every (re)connect because tickets are single-use (PR-023 F01).
    const protocols = isCrossOriginHttp()
      ? async () => [await requestRuntimeTicket()]
      : undefined;
    socket.connect(runtimeWsUrl(), protocols);
  }
});

onBeforeUnmount(() => {
  if (timer !== null) clearInterval(timer);
  socket?.disconnect();
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
          <span class="status-chip" :class="(runtime.status?.storage_mode ?? 'NORMAL') !== 'NORMAL' ? 'status-chip--warning' : 'status-chip--ready'">Disk {{ runtime.status ? formatBytes(runtime.status.disk_free_bytes) + " free · " + (runtime.status.storage_mode ?? "NORMAL") : "unknown" }}</span>
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
  color: var(--text);
  font-size: 24px;
}
.live-inspection__eyebrow { margin: 0 0 3px; color: var(--accent); font-family: var(--font-mono); font-size: 11px; font-weight: 800; letter-spacing: 0.1em; }
.live-inspection__sn {
  color: var(--text-muted);
  font-size: 14px;
}
.live-inspection__inspection-id {
  color: var(--text-faint);
  font-size: 12px;
}
.live-inspection__strips { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px; }
.status-strip { border: 1px solid var(--border); border-left: 4px solid var(--accent); border-radius: var(--radius); background: var(--surface-raised); padding: 11px 12px; box-shadow: var(--shadow); }
.status-strip h3 { margin: 0 0 8px; color: var(--text-muted); font-family: var(--font-mono); font-size: 11px; letter-spacing: 0.05em; text-transform: uppercase; }
.status-strip__items { display: flex; flex-wrap: wrap; gap: 7px; }
.status-chip { border-radius: var(--radius-small); padding: 4px 7px; font-size: 12px; font-weight: 650; }
.status-chip--ready { background: var(--status-ok-soft); color: var(--status-ok); }
.status-chip--critical { background: var(--status-ng-soft); color: var(--status-ng); }
.status-chip--warning { background: var(--status-warning-soft); color: var(--status-warning); }
.status-chip--neutral { background: var(--surface-muted); color: var(--text-muted); }
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
  border-radius: var(--radius-small);
}
.live-inspection__viewer {
  height: 46vh;
  min-height: 280px;
  border: 1px solid var(--border);
  border-radius: var(--radius-small);
}
.live-inspection__unavailable {
  height: 100%;
  min-height: 280px;
  display: flex;
  align-items: center;
  justify-content: center;
}
.panel {
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: var(--panel-padding);
  background: var(--surface-raised);
  box-shadow: var(--shadow);
}
.panel h3 {
  margin: 0 0 10px;
  font-size: 14px;
  color: var(--text);
}
.info-dl {
  display: grid;
  grid-template-columns: 110px 1fr;
  gap: 6px 12px;
  font-size: 13px;
  margin: 0;
}
.info-dl dt {
  color: var(--text-muted);
}
.info-dl dd {
  margin: 0;
  word-break: break-all;
}
.rule {
  display: inline-block;
  border-radius: var(--radius-small);
  padding: 1px 10px;
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

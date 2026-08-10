<script setup lang="ts">
// Live inspection view: camera feed, latest result, evidence overlays,
// readiness and connectivity strips, recent results, and runtime logs
// (docs/design/16-edge-dashboard.md 16.4).

import type { InspectionImages, InspectionSummary, LogEvent, WSEventEnvelope } from "@assemblyvision/api-client";
import {
  DetectionViewer,
  StatusBadge,
  formatBytes,
  formatIsoTime,
  formatLatency,
  toDecisionStatus,
} from "@assemblyvision/ui";
import type { ViewerBox } from "@assemblyvision/ui";
import { ReconnectingWebSocket } from "@assemblyvision/api-client";
import { computed, onBeforeUnmount, onMounted, ref } from "vue";
import { useI18n } from "vue-i18n";
import { mockCameraFrame } from "../mock/images";
import { useInspectionStore } from "../stores/inspection";
import { useRuntimeStore } from "../stores/runtime";
import {
  getApiBaseUrl,
  getRuntimeWsUrl,
  isCrossOriginHttp,
  isHttpMode,
  isMockMode,
  loadMediaBlobUrl,
  requestRuntimeTicket,
} from "../services/client";
import { inspectionService } from "../services/inspectionService";

const { t } = useI18n();
const store = useInspectionStore();
const runtime = useRuntimeStore();
const images = ref<InspectionImages | null>(null);
const logs = ref<LogEvent[]>([]);
const latestResult = ref<InspectionSummary | null>(null);
const recentResults = ref<InspectionSummary[]>([]);
const httpCameraFrame = ref<string | null>(null);
const lastPreviewFrameAt = ref<string | null>(null);
const now = ref(Date.now());
let timer: ReturnType<typeof setInterval> | null = null;
let clockTimer: ReturnType<typeof setInterval> | null = null;
let cameraTimer: ReturnType<typeof setInterval> | null = null;
let socket: ReconnectingWebSocket | null = null;
let previewSeq = 0;

// In real mode there is no live operator window (M1, ADR-012): the view is
// driven by the camera preview, device status, and completed inspections, and
// the mock current-inspection store is never used (F6, design 16.11). Media
// that is absent or unreachable renders as an explicit unavailable state.
const isMock = isMockMode();
const isHttp = isHttpMode();

// The per-instance REST preview (design 16.4.3, ADR-013) needs the configured
// camera instance id, which the aggregated device status does not carry. It is
// read from VITE_CAMERA_INSTANCE_ID and defaults to the example single-line
// instance; fleet deployments must set the variable per line.
const CAMERA_INSTANCE_ID =
  (import.meta.env.VITE_CAMERA_INSTANCE_ID as string | undefined) ?? "line-1";

const cameraFrame = computed(() => (isHttp ? httpCameraFrame.value : mockCameraFrame(800, 600)));
const cameraWidth = computed(() => runtime.camera?.source_width ?? 800);
const cameraHeight = computed(() => runtime.camera?.source_height ?? 600);
const detectionUrl = computed(() => images.value?.detection || cameraFrame.value || null);
const annotatedUrl = computed(() => images.value?.annotated || cameraFrame.value || null);

// Overlays exist only for the operator workflow's mock evidence; real mode has
// no source-coordinate overlay stream, so the camera and latest evidence are
// shown without boxes (16.4.1).
const overlayBoxes = computed<ViewerBox[]>(() => (isHttp ? [] : mockBoxes.value));

const mockBoxes = computed<ViewerBox[]>(() => {
  const id = store.current?.inspection_id ?? "frame";
  const boxes: ViewerBox[] = [];
  if (store.current?.status === "NG") {
    boxes.push({ id: "manual", kind: "component", label: t("manual (missing)"), box: { x_min: 500, y_min: 420, x_max: 620, y_max: 480 }, frameId: id });
  } else if (store.current?.status === "PASS" || store.current?.status === "PROCESSING") {
    boxes.push({ id: "product", kind: "product", label: t("product"), box: { x_min: 120, y_min: 90, x_max: 680, y_max: 520 }, frameId: id });
  }
  boxes.push({ id: "roi", kind: "roi", label: t("ROI"), box: { x_min: 80, y_min: 60, x_max: 720, y_max: 550 }, frameId: id });
  return boxes;
});

const currentFrameId = computed(() => (store.current?.inspection_id ?? "frame") as string);

const badgeStatus = computed(() => {
  if (isHttp) {
    return latestResult.value
      ? toDecisionStatus(latestResult.value.business_result, latestResult.value.internal_decision)
      : "UNCERTAIN";
  }
  const s = store.current?.status ?? "WAITING";
  if (s === "PASS") return "OK";
  if (s === "NG") return "NG";
  return "UNCERTAIN";
});

const headerSn = computed(() => (isHttp ? latestResult.value?.sn : store.current?.sn) ?? "waiting");
const headerInspectionId = computed(() =>
  isHttp ? latestResult.value?.inspection_id : store.current?.inspection_id,
);

// Local API freshness: green only while the last successful snapshot refresh is
// recent and error-free; otherwise the connectivity chip reports stale and the
// stored snapshot is never presented as current (16.11).
const lastUpdatedTime = computed(() =>
  runtime.lastUpdatedAt ? formatClock(runtime.lastUpdatedAt) : "—",
);
const localApiFresh = computed(() => {
  if (!runtime.lastUpdatedAt || runtime.error) return false;
  return now.value - new Date(runtime.lastUpdatedAt).getTime() < 5000;
});

// The frame timestamp is the camera capture time when the backend provides it,
// otherwise the last successfully received preview frame. A preview that stops
// delivering frames for more than 3s renders as stale (16.4.1).
const frameTimestamp = computed(() => runtime.camera?.last_frame_at ?? lastPreviewFrameAt.value ?? null);
const isCameraStale = computed(() => {
  const ts = frameTimestamp.value;
  if (!ts) return false;
  return now.value - new Date(ts).getTime() > 3000;
});

function formatClock(iso: string): string {
  const d = new Date(iso);
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`;
}

async function loadImages(): Promise<void> {
  const id = isHttp ? latestResult.value?.inspection_id : store.current?.inspection_id;
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

async function loadHistory(): Promise<void> {
  try {
    const [latestPage, recentPage] = await Promise.all([
      inspectionService.listHistory({ limit: 1 }),
      inspectionService.listHistory({ limit: 10 }),
    ]);
    latestResult.value = latestPage.items[0] ?? null;
    recentResults.value = recentPage.items;
  } catch {
    // keep the last known result and recent rail
  }
}

async function refresh(): Promise<void> {
  if (!isHttp) await store.loadCurrent();
  await runtime.refresh();
  await loadHistory();
  await Promise.all([loadImages(), loadLogs()]);
}

// Preview polling is best-effort: the server re-encodes the JPEG at most every
// _PREVIEW_MIN_INTERVAL_S per instance, so 1500ms keeps the panel fresh without
// saturating the edge CPU (ADR-013). Old object URLs are revoked so the page
// never leaks blob memory.
async function pollCameraPreview(): Promise<void> {
  if (!isHttp) return;
  const seq = ++previewSeq;
  const url = `${getApiBaseUrl()}/api/v1/camera/${CAMERA_INSTANCE_ID}/preview`;
  try {
    const blobUrl = await loadMediaBlobUrl(url);
    if (seq !== previewSeq) {
      URL.revokeObjectURL(blobUrl);
      return;
    }
    if (httpCameraFrame.value) URL.revokeObjectURL(httpCameraFrame.value);
    httpCameraFrame.value = blobUrl;
    lastPreviewFrameAt.value = new Date().toISOString();
  } catch {
    // Keep the last frame; preview loss never changes the inspection engine
    // state and the stale marker takes over (16.4.3).
  }
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
  // A live clock keeps the local-API freshness chip and the stale-frame marker
  // accurate between snapshot refreshes.
  clockTimer = setInterval(() => {
    now.value = Date.now();
  }, 1000);
  if (isHttp) {
    void pollCameraPreview();
    cameraTimer = setInterval(() => void pollCameraPreview(), 1500);
  }
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
  if (clockTimer !== null) clearInterval(clockTimer);
  if (cameraTimer !== null) clearInterval(cameraTimer);
  socket?.disconnect();
  if (httpCameraFrame.value) {
    URL.revokeObjectURL(httpCameraFrame.value);
    httpCameraFrame.value = null;
  }
});
</script>

<template>
  <div class="live-inspection">
    <div class="live-inspection__head">
      <div>
        <p class="live-inspection__eyebrow">{{ t("LOCAL INSPECTION") }}</p>
        <h2>{{ t("Live inspection") }}</h2>
      </div>
      <StatusBadge :status="badgeStatus" />
      <span class="live-inspection__sn">{{ headerSn }}</span>
      <span class="live-inspection__inspection-id">{{ headerInspectionId }}</span>
    </div>

    <div v-if="!isHttp" class="live-inspection__progress">
      <el-progress
        :percentage="Math.round((store.current?.progress ?? 0) * 100)"
        :stroke-width="10"
      />
    </div>

    <el-alert
      v-if="runtime.error"
      :title="runtime.error"
      type="error"
      show-icon
      :closable="false"
    />

    <div class="live-inspection__strips" :aria-label="t('Inspection readiness and connectivity')">
      <section class="status-strip">
        <h3>{{ t("Inspection readiness") }}</h3>
        <div class="status-strip__items">
          <span class="status-chip" :class="runtime.status?.inspection_ready ? 'status-chip--ready' : 'status-chip--critical'">{{ t("Engine {state}", { state: runtime.status?.inspection_ready ? t("ready") : t("not ready") }) }}</span>
          <span class="status-chip" :class="runtime.status?.camera_connected ? 'status-chip--ready' : 'status-chip--critical'">{{ t("Camera {state}", { state: runtime.status?.camera_connected ? t("connected") : t("offline") }) }}</span>
          <span class="status-chip" :class="runtime.status?.model_loaded ? 'status-chip--ready' : 'status-chip--critical'">{{ t("Model {state}", { state: runtime.status?.model_loaded ? t("loaded") : t("unavailable") }) }}</span>
          <span class="status-chip" :class="runtime.status?.current_rule_version_id ? 'status-chip--ready' : 'status-chip--critical'">{{ t("Rule {state}", { state: runtime.status?.current_rule_version_id ? t("loaded") : t("missing") }) }}</span>
          <span class="status-chip" :class="(runtime.status?.storage_mode ?? 'NORMAL') !== 'NORMAL' ? 'status-chip--warning' : 'status-chip--ready'">{{ runtime.status ? t("Disk {bytes} free · {mode}", { bytes: formatBytes(runtime.status.disk_free_bytes), mode: runtime.status.storage_mode ?? "NORMAL" }) : t("unknown") }}</span>
        </div>
      </section>
      <section class="status-strip">
        <h3>{{ t("Connectivity") }}</h3>
        <div class="status-strip__items">
          <span class="status-chip" :class="localApiFresh ? 'status-chip--ready' : 'status-chip--neutral'">{{ t("Local API {state}", { state: localApiFresh ? t("available") : t("stale") }) }}</span>
          <span class="status-chip" :class="runtime.status?.central_connected ? 'status-chip--ready' : 'status-chip--warning'">{{ t("Central {state}", { state: runtime.status?.central_connected ? t("connected") : t("offline") }) }}</span>
          <span class="status-chip status-chip--neutral">{{ t("Uploads pending {count}", { count: runtime.status?.upload_pending_count ?? "-" }) }}</span>
        </div>
        <p class="live-inspection__updated">{{ t("Last updated {time}", { time: lastUpdatedTime }) }}</p>
      </section>
    </div>

    <div class="live-inspection__grid">
      <section class="panel">
        <h3>{{ t("Camera image") }}</h3>
        <div class="live-inspection__viewer">
          <DetectionViewer
            v-if="cameraFrame"
            :image-url="cameraFrame"
            :image-width="cameraWidth"
            :image-height="cameraHeight"
            :boxes="[]"
            :current-frame-id="null"
            :last-frame-at="frameTimestamp"
            :stale-after-ms="3000"
          />
          <div v-if="isCameraStale" class="live-inspection__stale" role="status">{{ t("STALE FRAME") }}</div>
          <el-empty
            v-else-if="!cameraFrame"
            :description="t('No camera feed available')"
            :image-size="72"
            class="live-inspection__unavailable"
          />
        </div>
      </section>

      <section class="panel">
        <h3>{{ t("Detection result") }}</h3>
        <div class="live-inspection__viewer">
          <DetectionViewer
            v-if="detectionUrl"
            :image-url="detectionUrl"
            :image-width="800"
            :image-height="600"
            :boxes="overlayBoxes"
            :current-frame-id="currentFrameId"
          />
          <el-empty
            v-else
            :description="t('No detection image available')"
            :image-size="72"
            class="live-inspection__unavailable"
          />
        </div>
      </section>

      <section class="panel">
        <h3>{{ t("Detection regions") }}</h3>
        <div class="live-inspection__viewer">
          <DetectionViewer
            v-if="annotatedUrl"
            :image-url="annotatedUrl"
            :image-width="800"
            :image-height="600"
            :boxes="overlayBoxes"
            :current-frame-id="currentFrameId"
          />
          <el-empty
            v-else
            :description="t('No annotated image available')"
            :image-size="72"
            class="live-inspection__unavailable"
          />
        </div>
      </section>
    </div>

    <div class="live-inspection__info" :class="{ 'live-inspection__info--single': isHttp }">
      <section v-if="isHttp" class="panel">
        <h3>{{ t("Latest result") }}</h3>
        <template v-if="latestResult">
          <StatusBadge :status="badgeStatus" />
          <dl class="info-dl">
            <dt>{{ t("Inspection ID") }}</dt>
            <dd>{{ latestResult.inspection_id }}</dd>
            <dt>{{ t("Barcode / SN") }}</dt>
            <dd>{{ latestResult.barcode ?? latestResult.sn ?? "—" }}</dd>
            <dt>{{ t("Product") }}</dt>
            <dd>{{ latestResult.product_code || "—" }}</dd>
            <dt>{{ t("Latency") }}</dt>
            <dd>{{ formatLatency(latestResult.latency_ms) }}</dd>
            <dt>{{ t("Completed") }}</dt>
            <dd>{{ formatIsoTime(latestResult.completed_at) }}</dd>
          </dl>
        </template>
        <el-empty
          v-else
          :description="t('No completed inspection yet')"
          :image-size="48"
          class="live-inspection__info-empty"
        />
      </section>

      <section v-else class="panel">
        <h3>{{ t("Inspection details") }}</h3>
        <dl class="info-dl">
          <dt>{{ t("Inspection ID") }}</dt>
          <dd>{{ store.current?.inspection_id }}</dd>
          <dt>{{ t("SN") }}</dt>
          <dd>{{ store.current?.sn ?? "—" }}</dd>
          <dt>{{ t("Product") }}</dt>
          <dd>{{ store.current?.product_code || "—" }}</dd>
          <dt>{{ t("Operator") }}</dt>
          <dd>{{ store.current?.operator ?? "—" }}</dd>
          <dt>{{ t("Started") }}</dt>
          <dd>{{ formatIsoTime(store.current?.started_at) }}</dd>
          <dt>{{ t("Duration") }}</dt>
          <dd>{{ formatLatency(store.current?.duration_ms) }}</dd>
          <dt>{{ t("Status") }}</dt>
          <dd>{{ store.current?.status ?? "WAITING" }}</dd>
        </dl>
      </section>

      <section v-if="!isHttp" class="panel">
        <h3>{{ t("Rules") }}</h3>
        <el-table :data="store.current?.rules ?? []" size="small">
          <el-table-column prop="name" :label="t('Rule')" min-width="150" />
          <el-table-column :label="t('Status')" width="100">
            <template #default="{ row }">
              <span class="rule" :class="`rule--${row.status.toLowerCase()}`">{{ row.status }}</span>
            </template>
          </el-table-column>
          <el-table-column prop="result_message" :label="t('Result message')" min-width="160" />
        </el-table>
      </section>
    </div>

    <section class="panel live-inspection__recent">
      <h3>{{ t("Recent results") }}</h3>
      <div v-if="recentResults.length" class="live-inspection__rail">
        <router-link
          v-for="r in recentResults"
          :key="r.inspection_id"
          :to="`/inspections/${r.inspection_id}`"
          class="live-inspection__rail-item"
        >
          <StatusBadge :status="toDecisionStatus(r.business_result, r.internal_decision)" />
          <span class="live-inspection__rail-label">{{ r.sn ?? r.barcode ?? "—" }}</span>
          <span class="live-inspection__rail-time">{{ formatIsoTime(r.completed_at) }}</span>
        </router-link>
      </div>
      <el-empty
        v-else
        :description="t('No completed inspections yet')"
        :image-size="48"
        class="live-inspection__info-empty"
      />
    </section>

    <section class="panel live-inspection__logs">
      <h3>{{ t("Runtime logs") }}</h3>
      <el-table :data="logs" size="small" height="280">
        <el-table-column :label="t('Time')" width="150">
          <template #default="{ row }">{{ formatIsoTime(row.logged_at) }}</template>
        </el-table-column>
        <el-table-column prop="level" :label="t('Level')" width="70" />
        <el-table-column prop="component" :label="t('Component')" width="140" />
        <el-table-column prop="message" :label="t('Message')" min-width="200" />
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
.live-inspection__updated {
  margin: 8px 0 0;
  color: var(--text-faint);
  font-family: var(--font-mono);
  font-size: 11px;
}
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
.live-inspection__info--single {
  grid-template-columns: 1fr;
}
.live-inspection__recent {
  width: 100%;
}
.live-inspection__rail {
  display: flex;
  gap: 8px;
  overflow-x: auto;
  padding-bottom: 4px;
}
.live-inspection__rail-item {
  flex: 0 0 auto;
  display: flex;
  flex-direction: column;
  gap: 3px;
  min-width: 170px;
  padding: 8px 10px;
  border: 1px solid var(--border);
  border-radius: var(--radius-small);
  background: var(--surface);
  color: var(--text);
  text-decoration: none;
  font-size: 12px;
}
.live-inspection__rail-label {
  color: var(--text-muted);
  font-family: var(--font-mono);
  font-size: 11px;
}
.live-inspection__rail-time {
  color: var(--text-faint);
  font-size: 11px;
}
.live-inspection__logs {
  width: 100%;
}
.live-inspection__viewer {
  position: relative;
  height: 46vh;
  min-height: 280px;
  border: 1px solid var(--border);
  border-radius: var(--radius-small);
}
.live-inspection__stale {
  position: absolute;
  top: 8px;
  right: 8px;
  z-index: 1;
  background: var(--status-warning);
  color: var(--shell-text);
  font-size: 12px;
  font-weight: 600;
  padding: 4px 8px;
  border-radius: var(--radius-small);
}
.live-inspection__unavailable {
  height: 100%;
  min-height: 280px;
  display: flex;
  align-items: center;
  justify-content: center;
}
.live-inspection__info-empty {
  min-height: 96px;
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
  margin: 10px 0 0;
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

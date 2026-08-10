<script setup lang="ts">
import type { InspectionRecord, MediaKind, MediaMetadata } from "@assemblyvision/api-client";
import { ApiError } from "@assemblyvision/api-client";
import { DetectionViewer, StatusBadge, formatBytes, formatIsoTime, formatLatency, reasonCodeLabel, toDecisionStatus } from "@assemblyvision/ui";
import type { ViewerBox } from "@assemblyvision/ui";
import { computed, onBeforeUnmount, onMounted, ref, watch } from "vue";
import { useRoute } from "vue-router";
import ReviewPanel from "../components/ReviewPanel.vue";
import { getApiClient, isCrossOriginHttp, isMockMode } from "../services/client";
import { buildMediaUrl, inspectionService } from "../services/inspectionService";
import { placeholderFrame } from "../services/placeholder";

const route = useRoute();
const record = ref<InspectionRecord | null>(null);
const media = ref<MediaMetadata[]>([]);
const error = ref<string | null>(null);
const showProduct = ref(true);
const showRoi = ref(true);

const activeTabKey = ref<string | null>(null);
const videoFailed = ref(false);
const blobUrls = ref<Record<string, string>>({});
const failedIds = ref(new Set<string>());
let trackedBlobUrls = new Set<string>();

const isMock = isMockMode();
const crossOrigin = isCrossOriginHttp();

const IMAGE_KINDS: MediaKind[] = ["KEY_FRAME", "PRODUCT_ROI", "ANNOTATED_FRAME"];
const CLIP_KINDS: MediaKind[] = ["NG_CLIP", "ROLLING_VIDEO"];

const KIND_LABELS: Record<MediaKind, string> = {
  KEY_FRAME: "Key frame",
  PRODUCT_ROI: "Product ROI",
  ANNOTATED_FRAME: "Annotated",
  NG_CLIP: "Clip",
  ROLLING_VIDEO: "Clip",
};

type MediaTab = { key: string; label: string; kinds: MediaKind[]; media: MediaMetadata; isVideo: boolean };

onMounted(async () => {
  const id = String(route.params.id);
  try {
    record.value = await getApiClient().getInspection(id);
    media.value = await getApiClient().listInspectionMedia(id);
  } catch (err) {
    error.value = err instanceof ApiError ? err.message : String(err);
  }
});

onBeforeUnmount(() => {
  for (const url of trackedBlobUrls) URL.revokeObjectURL(url);
  trackedBlobUrls = new Set<string>();
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

function firstAvailable(kind: MediaKind): MediaMetadata | undefined {
  return media.value.find((m) => m.kind === kind && m.lifecycle === "AVAILABLE");
}

const mediaTabs = computed<MediaTab[]>(() => {
  if (isMock) return [];
  const tabs: MediaTab[] = [];
  for (const kind of IMAGE_KINDS) {
    const item = firstAvailable(kind);
    if (item) tabs.push({ key: `img-${kind}`, label: KIND_LABELS[kind], kinds: [kind], media: item, isVideo: false });
  }
  const clip = CLIP_KINDS.map(firstAvailable).find((m) => m !== undefined);
  if (clip) tabs.push({ key: "clip", label: "Clip", kinds: [...CLIP_KINDS], media: clip, isVideo: true });
  return tabs;
});

const activeTab = computed<MediaTab | null>(() => mediaTabs.value.find((t) => t.key === activeTabKey.value) ?? null);
const activeMedia = computed<MediaMetadata | null>(() => activeTab.value?.media ?? null);
const activeIsVideo = computed(() => activeTab.value?.isVideo ?? false);

watch(mediaTabs, (tabs) => {
  if (!activeTabKey.value || !tabs.some((t) => t.key === activeTabKey.value)) {
    const preferred = tabs.find((t) => !t.isVideo) ?? tabs[0];
    activeTabKey.value = preferred?.key ?? null;
  }
}, { immediate: true });

async function resolveBlob(mediaId: string): Promise<string | null> {
  if (blobUrls.value[mediaId]) return blobUrls.value[mediaId];
  if (failedIds.value.has(mediaId)) return null;
  try {
    const url = await inspectionService.getMediaContentBlobUrl(mediaId);
    trackedBlobUrls.add(url);
    blobUrls.value = { ...blobUrls.value, [mediaId]: url };
    return url;
  } catch {
    failedIds.value = new Set([...failedIds.value, mediaId]);
    return null;
  }
}

function mediaSrc(m: MediaMetadata): string | null {
  if (m.lifecycle !== "AVAILABLE") return null;
  return crossOrigin ? (blobUrls.value[m.media_id] ?? null) : buildMediaUrl(m.media_id);
}

const activeSrc = computed<string | null>(() => (activeMedia.value ? mediaSrc(activeMedia.value) : null));

const keyFrameMedia = computed<MediaMetadata | null>(() => firstAvailable("KEY_FRAME") ?? null);
const keyFrameSrc = computed<string | null>(() => (keyFrameMedia.value ? mediaSrc(keyFrameMedia.value) : null));

watch(activeMedia, async (m) => {
  videoFailed.value = false;
  if (m && crossOrigin) await resolveBlob(m.media_id);
}, { immediate: true });

watch(keyFrameMedia, async (m) => {
  if (m && crossOrigin) await resolveBlob(m.media_id);
}, { immediate: true });

const evidenceImageUrl = computed<string>(() => {
  const src = activeIsVideo.value ? keyFrameSrc.value : activeSrc.value;
  return src ?? placeholderFrame(sourceSize.value.width, sourceSize.value.height);
});

function selectMedia(m: MediaMetadata): void {
  if (isMock) return;
  const tab = mediaTabs.value.find((t) => t.kinds.includes(m.kind));
  if (tab) activeTabKey.value = tab.key;
}

function mediaKindLabel(kind: MediaKind): string {
  return KIND_LABELS[kind];
}

const sourceLabel = computed<string>(() => {
  const det = record.value?.product_detection;
  return det ? `${det.bbox.image_width}×${det.bbox.image_height}` : "-";
});

const qualityLabel = computed<string>(() => {
  const q = record.value?.product_detection?.quality;
  if (!q) return "-";
  if (q.usable) return `usable · blur ${q.blur_score.toFixed(1)}`;
  return q.reason_codes.length ? `rejected · ${q.reason_codes.join(", ")}` : "rejected";
});
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
            <div v-if="mediaTabs.length" class="detail__tabs" role="tablist">
              <button
                v-for="tab in mediaTabs"
                :key="tab.key"
                class="detail__tab"
                :class="{ 'detail__tab--active': tab.key === activeTabKey }"
                role="tab"
                :aria-selected="tab.key === activeTabKey"
                type="button"
                @click="activeTabKey = tab.key"
              >
                {{ tab.label }}
              </button>
            </div>

            <DetectionViewer
              v-if="!activeIsVideo"
              :image-url="evidenceImageUrl"
              :image-width="sourceSize.width"
              :image-height="sourceSize.height"
              :boxes="overlayBoxes"
              :current-frame-id="currentFrameId"
            />
            <div v-else class="detail__clip">
              <video
                v-if="activeSrc && !videoFailed"
                :src="activeSrc"
                controls
                class="detail__clip-video"
                @error="videoFailed = true"
              ></video>
              <img
                v-else
                :src="evidenceImageUrl"
                alt="clip key-frame fallback"
                class="detail__clip-fallback"
              />
            </div>

            <div class="detail__viewer-controls">
              <el-checkbox v-model="showProduct" label="Product box" />
              <el-checkbox v-model="showRoi" label="ROI" />
            </div>
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
            <dt>Source</dt>
            <dd>{{ sourceLabel }}</dd>
            <dt>Frame quality</dt>
            <dd>{{ qualityLabel }}</dd>
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
              <button
                v-if="m.lifecycle === 'AVAILABLE' && !isMock"
                class="detail__media-row"
                :class="{ 'detail__media-row--active': m.media_id === activeMedia?.media_id }"
                type="button"
                @click="selectMedia(m)"
              >
                <span class="detail__media-kind">{{ mediaKindLabel(m.kind) }}</span>
                <span class="detail__media-size">{{ formatBytes(m.size_bytes) }}</span>
              </button>
              <div v-else class="detail__media-row detail__media-row--muted">
                <span class="detail__media-kind">{{ mediaKindLabel(m.kind) }}</span>
                <span class="detail__media-size">{{ formatBytes(m.size_bytes) }}</span>
                <span v-if="m.lifecycle === 'PURGED'" class="pill pill--warn">purged</span>
                <span v-else-if="m.lifecycle === 'FAILED'" class="pill pill--failed">failed</span>
                <span v-else-if="m.lifecycle === 'PENDING'" class="pill pill--pending">pending</span>
                <span v-else class="pill pill--present">available</span>
              </div>
              <p v-if="m.lifecycle === 'PURGED'" class="detail__media-note">Content is not retained</p>
              <p v-if="m.lifecycle === 'FAILED'" class="detail__media-note">Capture or storage failed</p>
            </li>
            <li v-if="!media.length">No media</li>
          </ul>
        </aside>
      </div>

      <ReviewPanel
        v-if="record"
        :inspection-id="record.inspection_id"
        :business-result="record.decision.business_result"
        :internal-decision="record.decision.internal_decision"
      />
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
.detail__viewer-controls {
  display: flex;
  gap: 12px;
}
.detail__tabs {
  display: flex;
  gap: 4px;
  flex-wrap: wrap;
}
.detail__tab {
  background: var(--surface-muted);
  color: var(--text-muted);
  border: 1px solid var(--border);
  border-radius: var(--radius-small);
  padding: 3px 10px;
  font-size: 12px;
  cursor: pointer;
}
.detail__tab:hover {
  border-color: var(--border-strong);
}
.detail__tab--active {
  background: var(--status-info-soft);
  color: var(--status-info);
  border-color: var(--status-info);
}
.detail__clip {
  flex: 1;
  min-height: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  background: var(--surface-inset);
  overflow: hidden;
}
.detail__clip-video {
  width: 100%;
  height: 100%;
  object-fit: contain;
}
.detail__clip-fallback {
  max-width: 100%;
  max-height: 100%;
  object-fit: contain;
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
.detail__media li {
  display: flex;
  flex-direction: column;
  gap: 2px;
  margin-bottom: 6px;
}
.detail__media-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  width: 100%;
  border: 1px solid var(--border);
  border-radius: var(--radius-small);
  background: var(--surface-raised);
  padding: 4px 8px;
  font-size: 13px;
  text-align: left;
  cursor: pointer;
}
.detail__media-row:hover {
  border-color: var(--border-strong);
}
.detail__media-row--active {
  border-color: var(--status-info);
  background: var(--status-info-soft);
}
.detail__media-row--muted {
  cursor: default;
  border-style: dashed;
}
.detail__media-kind {
  overflow-wrap: anywhere;
}
.detail__media-size {
  color: var(--text-muted);
  white-space: nowrap;
}
.detail__media-note {
  margin: 0;
  font-size: 12px;
  color: var(--text-muted);
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
.pill--failed {
  background: var(--status-ng-soft);
  color: var(--status-ng);
}
.pill--pending {
  background: var(--status-info-soft);
  color: var(--status-info);
}
</style>

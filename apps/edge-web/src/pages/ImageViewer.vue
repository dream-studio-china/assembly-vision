<script setup lang="ts">
// Inspection media viewer: real key-frame, product ROI, annotated-frame, and
// clip content for one inspection (docs/design/16-edge-dashboard.md 16.5).
// Videos use the static key frame as a fallback when they cannot load.
// Purged or failed media renders metadata only, never a broken image.

import type { InspectionRecord, MediaKind, MediaMetadata } from "@assemblyvision/api-client";
import { ApiError } from "@assemblyvision/api-client";
import { formatBytes, formatIsoTime } from "@assemblyvision/ui";
import { computed, onBeforeUnmount, onMounted, ref, watch } from "vue";
import { useI18n } from "vue-i18n";
import { useRoute } from "vue-router";
import { getApiClient, isCrossOriginHttp, isMockMode } from "../services/client";
import { buildMediaUrl, inspectionService } from "../services/inspectionService";
import { mockCameraFrame } from "../mock/images";
import { placeholderFrame } from "../services/placeholder";

const { t } = useI18n();
const route = useRoute();
const record = ref<InspectionRecord | null>(null);
const media = ref<MediaMetadata[]>([]);
const error = ref<string | null>(null);
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

function firstAvailable(kind: MediaKind): MediaMetadata | undefined {
  return media.value.find((m) => m.kind === kind && m.lifecycle === "AVAILABLE");
}

const mediaTabs = computed<MediaTab[]>(() => {
  const tabs: MediaTab[] = [];
  for (const kind of IMAGE_KINDS) {
    const item = firstAvailable(kind);
    if (item) tabs.push({ key: `img-${kind}`, label: t(KIND_LABELS[kind]), kinds: [kind], media: item, isVideo: false });
  }
  const clip = CLIP_KINDS.map(firstAvailable).find((m) => m !== undefined);
  if (clip) tabs.push({ key: "clip", label: t("Clip"), kinds: [...CLIP_KINDS], media: clip, isVideo: true });
  return tabs;
});

const activeTab = computed<MediaTab | null>(() => mediaTabs.value.find((t) => t.key === activeTabKey.value) ?? null);
const activeIsVideo = computed(() => activeTab.value?.isVideo ?? false);

watch(mediaTabs, (tabs) => {
  if (!activeTabKey.value || !tabs.some((t) => t.key === activeTabKey.value)) {
    activeTabKey.value = tabs[0]?.key ?? null;
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
  if (isMock) {
    return m.kind === "KEY_FRAME" || m.kind === "PRODUCT_ROI" || m.kind === "ANNOTATED_FRAME"
      ? mockCameraFrame(800, 600)
      : null;
  }
  // Images always load through a fetch-backed blob URL so a missing file
  // settles deterministically into the unavailable state (design 16.11);
  // same-origin videos keep the raw URL so Range requests work, with the
  // key frame as the load-failure fallback.
  const isClip = m.kind === "NG_CLIP" || m.kind === "ROLLING_VIDEO";
  if (isClip && !crossOrigin) return buildMediaUrl(m.media_id);
  return blobUrls.value[m.media_id] ?? null;
}

const activeSrc = computed<string | null>(() => (activeTab.value ? mediaSrc(activeTab.value.media) : null));
const activeImageFailed = computed<boolean>(
  () =>
    !!activeTab.value &&
    !activeTab.value.isVideo &&
    failedIds.value.has(activeTab.value.media.media_id),
);

const keyFrameMedia = computed<MediaMetadata | null>(() => firstAvailable("KEY_FRAME") ?? null);
const keyFrameSrc = computed<string | null>(() => (keyFrameMedia.value ? mediaSrc(keyFrameMedia.value) : null));

watch(activeTab, async (tab) => {
  videoFailed.value = false;
  if (!tab) return;
  const isClip = tab.media.kind === "NG_CLIP" || tab.media.kind === "ROLLING_VIDEO";
  if (!isClip || crossOrigin) await resolveBlob(tab.media.media_id);
}, { immediate: true });

watch(keyFrameMedia, async (m) => {
  if (m) await resolveBlob(m.media_id);
}, { immediate: true });

const fallbackSrc = computed<string>(() => keyFrameSrc.value ?? placeholderFrame(800, 600));

function mediaKindLabel(kind: MediaKind): string {
  return t(KIND_LABELS[kind]);
}

function selectMedia(m: MediaMetadata): void {
  const tab = mediaTabs.value.find((t) => t.kinds.includes(m.kind));
  if (tab) activeTabKey.value = tab.key;
}
</script>

<template>
  <div class="images">
    <el-alert v-if="error" :title="error" type="error" show-icon :closable="false" />
    <h2>{{ t("Inspection media") }}</h2>
    <p class="images__meta">
      {{ t("Inspection {id}", { id: route.params.id }) }}
      <template v-if="record">
        · {{ record.decision.business_result }} · {{ formatIsoTime(record.completed_at) }}
      </template>
    </p>

    <div v-if="mediaTabs.length" class="images__tabs" role="tablist">
      <button
        v-for="tab in mediaTabs"
        :key="tab.key"
        class="images__tab"
        :class="{ 'images__tab--active': tab.key === activeTabKey }"
        role="tab"
        :aria-selected="tab.key === activeTabKey"
        type="button"
        @click="activeTabKey = tab.key"
      >
        {{ tab.label }}
      </button>
    </div>

    <div v-if="media.length" class="images__stage">
      <video
        v-if="activeIsVideo && activeSrc && !videoFailed"
        :src="activeSrc"
        controls
        class="images__img"
        @error="videoFailed = true"
      ></video>
      <img
        v-else-if="activeTab && !activeTab.isVideo && activeSrc"
        :src="activeSrc"
        :alt="t('inspection media')"
        class="images__img"
      />
      <el-empty
        v-else-if="activeTab && !activeTab.isVideo && activeImageFailed"
        :description="t('Media content unavailable')"
      />
      <el-empty v-else-if="activeTab && activeIsVideo && videoFailed && !keyFrameSrc" :description="t('Media content unavailable')" />
      <img
        v-else-if="activeTab && activeIsVideo && videoFailed"
        :src="fallbackSrc"
        :alt="t('inspection media fallback')"
        class="images__img"
      />
      <el-empty v-else-if="activeTab" :description="t('Loading media…')" />
      <el-empty v-else :description="t('No available media')" />
    </div>
    <el-empty v-else :description="t('No media')" />

    <h3>{{ t("Media") }}</h3>
    <ul class="images__media">
      <li v-for="m in media" :key="m.media_id">
        <button
          v-if="m.lifecycle === 'AVAILABLE'"
          class="images__media-row"
          :class="{ 'images__media-row--active': m.media_id === activeTab?.media.media_id }"
          type="button"
          @click="selectMedia(m)"
        >
          <span class="images__media-kind">{{ mediaKindLabel(m.kind) }}</span>
          <span class="images__media-size">{{ formatBytes(m.size_bytes) }}</span>
        </button>
        <div v-else class="images__media-row images__media-row--muted">
          <span class="images__media-kind">{{ mediaKindLabel(m.kind) }}</span>
          <span class="images__media-size">{{ formatBytes(m.size_bytes) }}</span>
          <span v-if="m.lifecycle === 'PURGED'" class="pill pill--warn">{{ t("purged") }}</span>
          <span v-else-if="m.lifecycle === 'FAILED'" class="pill pill--failed">{{ t("failed") }}</span>
          <span v-else-if="m.lifecycle === 'PENDING'" class="pill pill--pending">{{ t("pending") }}</span>
          <span v-else class="pill pill--present">{{ t("available") }}</span>
        </div>
        <p v-if="m.lifecycle === 'PURGED'" class="images__media-note">{{ t("Content is not retained") }}</p>
        <p v-if="m.lifecycle === 'FAILED'" class="images__media-note">{{ t("Capture or storage failed") }}</p>
      </li>
      <li v-if="!media.length">{{ t("No media") }}</li>
    </ul>
  </div>
</template>

<style scoped>
.images {
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.images__meta {
  color: var(--text-muted);
  font-size: 13px;
}
.images__tabs {
  display: flex;
  gap: 4px;
  flex-wrap: wrap;
}
.images__tab {
  background: var(--surface-muted);
  color: var(--text-muted);
  border: 1px solid var(--border);
  border-radius: var(--radius-small);
  padding: 3px 10px;
  font-size: 12px;
  cursor: pointer;
}
.images__tab:hover {
  border-color: var(--border-strong);
}
.images__tab--active {
  background: var(--status-info-soft);
  color: var(--status-info);
  border-color: var(--status-info);
}
.images__stage {
  border: 1px solid var(--border);
  border-radius: var(--radius);
  background: var(--surface-inset);
  display: flex;
  align-items: center;
  justify-content: center;
  min-height: 280px;
  padding: 8px;
}
.images__img {
  max-width: 100%;
  max-height: 64vh;
  object-fit: contain;
}
.images__media {
  margin: 0;
  padding: 0;
  list-style: none;
  font-size: 13px;
  max-width: 820px;
}
.images__media li {
  display: flex;
  flex-direction: column;
  gap: 2px;
  margin-bottom: 6px;
}
.images__media-row {
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
.images__media-row:hover {
  border-color: var(--border-strong);
}
.images__media-row--active {
  border-color: var(--status-info);
  background: var(--status-info-soft);
}
.images__media-row--muted {
  cursor: default;
  border-style: dashed;
}
.images__media-kind {
  overflow-wrap: anywhere;
}
.images__media-size {
  color: var(--text-muted);
  white-space: nowrap;
}
.images__media-note {
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

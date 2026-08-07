<script setup lang="ts">
// Detection viewer: camera/static preview with product, component, and ROI
// overlays (docs/design/16-edge-dashboard.md 16.4.1 and 16.4.3).
//
// Overlays arrive in source-image coordinates and are mapped to the view with
// contain scaling. Overlays whose frame ID does not match the displayed frame
// are discarded, and a stale marker shows when the frame is older than
// `staleAfterMs`. Preview loss never affects the inspection engine state.

import { computed, onBeforeUnmount, onMounted, ref } from "vue";
import { boxToRect, clipToImageRect, containFit } from "./geometry";
import type { Rect } from "./geometry";
import { OVERLAY_COLORS } from "./types";
import type { ViewerBox } from "./types";

const props = withDefaults(
  defineProps<{
    imageUrl: string | null;
    imageWidth: number;
    imageHeight: number;
    boxes: ViewerBox[];
    currentFrameId: string | null;
    lastFrameAt?: string | null;
    staleAfterMs?: number;
  }>(),
  { lastFrameAt: null, staleAfterMs: 3000 },
);

const container = ref<HTMLElement | null>(null);
const viewSize = ref<{ width: number; height: number }>({ width: 0, height: 0 });
let observer: ResizeObserver | null = null;

onMounted(() => {
  if (!container.value) return;
  observer = new ResizeObserver((entries) => {
    const entry = entries[0];
    if (entry) {
      viewSize.value = { width: entry.contentRect.width, height: entry.contentRect.height };
    }
  });
  observer.observe(container.value);
});

onBeforeUnmount(() => observer?.disconnect());

const sourceSize = computed(() => ({ width: props.imageWidth, height: props.imageHeight }));

const fit = computed(() => containFit(sourceSize.value, viewSize.value));

const imageStyle = computed(() => ({
  left: `${fit.value.offsetX}px`,
  top: `${fit.value.offsetY}px`,
  width: `${props.imageWidth * fit.value.scale}px`,
  height: `${props.imageHeight * fit.value.scale}px`,
}));

/** Only overlays belonging to the displayed frame are rendered (16.4.3). */
const visibleBoxes = computed<ViewerBox[]>(() =>
  props.currentFrameId === null ? [] : props.boxes.filter((b) => b.frameId === props.currentFrameId),
);

function rectFor(box: ViewerBox): Rect {
  const raw = boxToRect(box.box, sourceSize.value, viewSize.value);
  return clipToImageRect(raw, sourceSize.value, viewSize.value);
}

const isStale = computed(() => {
  if (!props.lastFrameAt) return false;
  const age = Date.now() - new Date(props.lastFrameAt).getTime();
  return Number.isFinite(age) && age > props.staleAfterMs;
});
</script>

<template>
  <div class="detection-viewer" ref="container">
    <div v-if="!imageUrl" class="detection-viewer__empty">No preview available</div>

    <template v-else>
      <img
        class="detection-viewer__image"
        :src="imageUrl"
        :style="imageStyle"
        alt="camera preview"
      />
      <div
        v-for="box in visibleBoxes"
        :key="box.id"
        class="detection-viewer__box"
        :style="{
          left: `${rectFor(box).x}px`,
          top: `${rectFor(box).y}px`,
          width: `${rectFor(box).width}px`,
          height: `${rectFor(box).height}px`,
          borderColor: OVERLAY_COLORS[box.kind],
        }"
      >
        <span class="detection-viewer__label" :style="{ background: OVERLAY_COLORS[box.kind] }">
          {{ box.label }}
        </span>
      </div>
      <div v-if="isStale" class="detection-viewer__stale" role="status">STALE FRAME</div>
    </template>
  </div>
</template>

<style scoped>
.detection-viewer {
  position: relative;
  width: 100%;
  height: 100%;
  min-height: 120px;
  overflow: hidden;
  background: #0f1115;
}
.detection-viewer__empty {
  position: absolute;
  inset: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  color: #8b93a1;
  font-size: 14px;
}
.detection-viewer__image {
  position: absolute;
  display: block;
}
.detection-viewer__box {
  position: absolute;
  border: 2px solid;
  box-sizing: border-box;
}
.detection-viewer__label {
  position: absolute;
  top: -20px;
  left: 0;
  color: #fff;
  font-size: 11px;
  line-height: 18px;
  padding: 0 6px;
  white-space: nowrap;
  border-radius: 2px;
}
.detection-viewer__stale {
  position: absolute;
  top: 8px;
  right: 8px;
  background: #ff6d00;
  color: #fff;
  font-size: 12px;
  font-weight: 600;
  padding: 4px 8px;
  border-radius: 3px;
}
</style>

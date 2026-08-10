<script setup lang="ts">
// Inspection image management: original, detection result, and annotated
// images for one inspection. Images arrive from the API as URLs plus a
// per-slot lifecycle status; the mock returns local SVG frames.
//
// In real mode (F14) missing or purged evidence renders an explicit
// unavailable/purged state, never a fabricated frame or a broken image.

import { computed, onMounted, ref } from "vue";
import { useRoute } from "vue-router";
import { inspectionService } from "../services/inspectionService";
import { isMockMode } from "../services/client";
import { mockCameraFrame } from "../mock/images";
import type { ImageSlotStatus, InspectionImages } from "@assemblyvision/api-client";

const route = useRoute();
const images = ref<InspectionImages | null>(null);
const error = ref<string | null>(null);
const failedSlots = ref(new Set<string>());

const isMock = isMockMode();

type Slot = { url: string | null; status: ImageSlotStatus };

function slot(kind: string, state: ImageSlotStatus | undefined, url: string | undefined): Slot {
  if (state === "PURGED") return { url: null, status: "PURGED" };
  if (failedSlots.value.has(kind)) return { url: null, status: "UNAVAILABLE" };
  if (url) return { url, status: "AVAILABLE" };
  return { url: isMock ? mockCameraFrame(800, 600) : null, status: "UNAVAILABLE" };
}

const slots = computed(() => ({
  original: slot("original", images.value?.original_status, images.value?.original),
  detection: slot("detection", images.value?.detection_status, images.value?.detection),
  annotated: slot("annotated", images.value?.annotated_status, images.value?.annotated),
}));

function markUnavailable(kind: string): void {
  failedSlots.value = new Set([...failedSlots.value, kind]);
}

function slotMessage(noun: string, status: ImageSlotStatus): string {
  return status === "PURGED" ? `${noun} evidence has been purged` : `No ${noun} image available`;
}

onMounted(async () => {
  try {
    images.value = await inspectionService.getImages(String(route.params.id));
  } catch (err) {
    error.value = String(err);
  }
});
</script>

<template>
  <div class="images">
    <el-alert v-if="error" :title="error" type="error" show-icon :closable="false" />
    <h2>Inspection images</h2>
    <p class="images__meta">Inspection {{ route.params.id }}</p>

    <el-tabs>
      <el-tab-pane label="Original">
        <img
          v-if="slots.original.url"
          :src="slots.original.url"
          alt="original frame"
          class="images__img"
          @error="markUnavailable('original')"
        />
        <el-empty
          v-else
          :description="slotMessage('original', slots.original.status)"
        />
      </el-tab-pane>
      <el-tab-pane label="Detection result">
        <img
          v-if="slots.detection.url"
          :src="slots.detection.url"
          alt="detection result"
          class="images__img"
          @error="markUnavailable('detection')"
        />
        <el-empty
          v-else
          :description="slotMessage('detection', slots.detection.status)"
        />
      </el-tab-pane>
      <el-tab-pane label="Annotations">
        <img
          v-if="slots.annotated.url"
          :src="slots.annotated.url"
          alt="annotated frame"
          class="images__img"
          @error="markUnavailable('annotated')"
        />
        <el-empty
          v-else
          :description="slotMessage('annotated', slots.annotated.status)"
        />
      </el-tab-pane>
    </el-tabs>
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
.images__img {
  width: 100%;
  max-width: 820px;
  border: 1px solid var(--border);
  border-radius: var(--radius);
}
</style>

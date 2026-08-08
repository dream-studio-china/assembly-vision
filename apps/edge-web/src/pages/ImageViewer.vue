<script setup lang="ts">
// Inspection image management: original, detection result, and annotated
// images for one inspection. Images arrive from the API as URLs; the mock
// returns local SVG frames.
//
// In real mode (F14) missing or purged evidence renders an explicit
// unavailable state, never a fabricated frame.

import { computed, onMounted, ref } from "vue";
import { useRoute } from "vue-router";
import { inspectionService } from "../services/inspectionService";
import { isMockMode } from "../services/client";
import { mockCameraFrame } from "../mock/images";
import type { InspectionImages } from "@assemblyvision/api-client";

const route = useRoute();
const images = ref<InspectionImages | null>(null);
const error = ref<string | null>(null);

const isMock = isMockMode();

function slotUrl(value: string | undefined): string | null {
  if (value) return value;
  return isMock ? mockCameraFrame(800, 600) : null;
}

const originalUrl = computed(() => slotUrl(images.value?.original));
const detectionUrl = computed(() => slotUrl(images.value?.detection));
const annotatedUrl = computed(() => slotUrl(images.value?.annotated));

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
          v-if="originalUrl"
          :src="originalUrl"
          alt="original frame"
          class="images__img"
        />
        <el-empty v-else description="No original image available" />
      </el-tab-pane>
      <el-tab-pane label="Detection result">
        <img
          v-if="detectionUrl"
          :src="detectionUrl"
          alt="detection result"
          class="images__img"
        />
        <el-empty v-else description="No detection image available" />
      </el-tab-pane>
      <el-tab-pane label="Annotations">
        <img
          v-if="annotatedUrl"
          :src="annotatedUrl"
          alt="annotated frame"
          class="images__img"
        />
        <el-empty v-else description="No annotated image available" />
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
  color: #6b7280;
  font-size: 13px;
}
.images__img {
  width: 100%;
  max-width: 820px;
  border: 1px solid #e0e0e0;
  border-radius: 6px;
}
</style>

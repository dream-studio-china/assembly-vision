<script setup lang="ts">
// Inspection image management: original, detection result, and annotated
// images for one inspection. Images arrive from the API as URLs; the mock
// returns local SVG frames.

import { onMounted, ref } from "vue";
import { useRoute } from "vue-router";
import { inspectionService } from "../services/inspectionService";
import { mockCameraFrame } from "../mock/images";
import type { InspectionImages } from "@assemblyvision/api-client";

const route = useRoute();
const images = ref<InspectionImages | null>(null);
const error = ref<string | null>(null);

const fallback = mockCameraFrame(800, 600);

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
        <img :src="images?.original ?? fallback" alt="original frame" class="images__img" />
      </el-tab-pane>
      <el-tab-pane label="Detection result">
        <img :src="images?.detection ?? fallback" alt="detection result" class="images__img" />
      </el-tab-pane>
      <el-tab-pane label="Annotations">
        <img :src="images?.annotated ?? fallback" alt="annotated frame" class="images__img" />
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

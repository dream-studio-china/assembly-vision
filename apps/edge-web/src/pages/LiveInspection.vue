<script setup lang="ts">
// Live inspection view: camera feed, detection result, detection region
// overlay, and inspection progress (docs/design/16-edge-dashboard.md 16.4).

import { DetectionViewer, StatusBadge } from "@assemblyvision/ui";
import type { ViewerBox } from "@assemblyvision/ui";
import { computed, onMounted, ref } from "vue";
import { mockCameraFrame } from "../mock/images";
import { useInspectionStore } from "../stores/inspection";
import { inspectionService } from "../services/inspectionService";
import type { InspectionImages } from "@assemblyvision/api-client";

const store = useInspectionStore();
const images = ref<InspectionImages | null>(null);

const badgeStatus = computed(() => {
  const s = store.current?.status ?? "WAITING";
  if (s === "PASS") return "OK";
  if (s === "NG") return "NG";
  return "UNCERTAIN";
});

const cameraFrame = computed(() => mockCameraFrame(800, 600));

const currentFrameId = computed(() => (store.current?.inspection_id ?? "frame") as string);

// Detection regions drawn over the detection image in source coordinates.
const detectionBoxes = computed<ViewerBox[]>(() => {
  const id = store.current?.inspection_id ?? "frame";
  if (store.current?.status === "NG") {
    return [
      { id: "manual", kind: "component", label: "manual (missing)", box: { x_min: 500, y_min: 420, x_max: 620, y_max: 480 }, frameId: id },
      { id: "roi", kind: "roi", label: "ROI", box: { x_min: 80, y_min: 60, x_max: 720, y_max: 550 }, frameId: id },
    ];
  }
  return [
    { id: "product", kind: "product", label: "product", box: { x_min: 120, y_min: 90, x_max: 680, y_max: 520 }, frameId: id },
    { id: "roi", kind: "roi", label: "ROI", box: { x_min: 80, y_min: 60, x_max: 720, y_max: 550 }, frameId: id },
  ];
});

onMounted(async () => {
  await store.loadCurrent();
  if (store.current?.inspection_id) {
    try {
      images.value = await inspectionService.getImages(store.current.inspection_id);
    } catch {
      images.value = null;
    }
  }
});
</script>

<template>
  <div class="live-inspection">
    <div class="live-inspection__head">
      <h2>Live inspection</h2>
      <StatusBadge :status="badgeStatus" />
      <span class="live-inspection__sn">{{ store.current?.sn ?? "waiting" }}</span>
    </div>

    <div class="live-inspection__progress">
      <el-progress
        :percentage="Math.round((store.current?.progress ?? 0) * 100)"
        :stroke-width="10"
      />
    </div>

    <div class="live-inspection__grid">
      <section class="panel">
        <h3>Camera image</h3>
        <div class="live-inspection__frame">
          <img :src="cameraFrame" alt="camera preview" />
        </div>
      </section>

      <section class="panel">
        <h3>Detection result</h3>
        <div class="live-inspection__viewer">
          <DetectionViewer
            :image-url="images?.detection ?? cameraFrame"
            :image-width="800"
            :image-height="600"
            :boxes="detectionBoxes"
            :current-frame-id="currentFrameId"
          />
        </div>
      </section>

      <section class="panel">
        <h3>Detection regions</h3>
        <div class="live-inspection__viewer">
          <DetectionViewer
            :image-url="images?.annotated ?? cameraFrame"
            :image-width="800"
            :image-height="600"
            :boxes="detectionBoxes"
            :current-frame-id="currentFrameId"
          />
        </div>
      </section>
    </div>
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
}
.live-inspection__head h2 {
  margin: 0;
}
.live-inspection__sn {
  color: #6b7280;
  font-size: 14px;
}
.live-inspection__grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 16px;
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
.panel {
  border: 1px solid #e0e0e0;
  border-radius: 6px;
  padding: 12px;
}
.panel h3 {
  margin: 0 0 10px;
  font-size: 14px;
  color: #374151;
}
</style>

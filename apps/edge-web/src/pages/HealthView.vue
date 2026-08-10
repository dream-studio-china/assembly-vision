<script setup lang="ts">
import { formatBytes } from "@assemblyvision/ui";
import * as echarts from "echarts";
import { computed, onMounted, ref } from "vue";
import EChart from "../components/EChart.vue";
import { getApiClient } from "../services/client";
import { chartTokens } from "../theme";
import type { DeviceStatus, UploadTask } from "@assemblyvision/api-client";

const status = ref<DeviceStatus | null>(null);
const uploads = ref<UploadTask[]>([]);
const error = ref<string | null>(null);

  const diskOption = computed<echarts.EChartsOption>(() => {
  const theme = chartTokens();
  const free = status.value?.disk_free_bytes ?? 0;
  const total = Math.max(free, 50 * 1024 ** 3);
  return {
    title: { text: "Disk usage", left: "center", textStyle: { fontSize: 14, color: theme.text } },
    series: [
      {
        type: "gauge",
        startAngle: 90,
        endAngle: -270,
        min: 0,
        max: total,
        progress: { show: true, width: 12 },
        axisLine: { lineStyle: { width: 12 } },
        axisLabel: { formatter: (value: number) => formatBytes(value) },
        data: [{ value: total - free, name: "Used" }],
        detail: { formatter: () => formatBytes(free) + " free", fontSize: 12 },
      },
    ],
  };
});

const queueOption = computed<echarts.EChartsOption>(() => {
  const theme = chartTokens();
  const byState: Record<string, number> = {};
  for (const task of uploads.value) {
    byState[task.status] = (byState[task.status] ?? 0) + 1;
  }
  return {
    title: { text: "Upload queue by state", left: "center", textStyle: { fontSize: 14, color: theme.text } },
    xAxis: { type: "category", data: Object.keys(byState), axisLine: { lineStyle: { color: theme.border } }, axisLabel: { color: theme.text } },
    yAxis: { type: "value", minInterval: 1, splitLine: { lineStyle: { color: theme.border } }, axisLabel: { color: theme.text } },
    series: [{ type: "bar", data: Object.values(byState), itemStyle: { color: theme.accent } }],
  };
});

onMounted(async () => {
  try {
    const [device, page] = await Promise.all([
      getApiClient().getDeviceStatus(),
      getApiClient().listUploads(undefined, 50),
    ]);
    status.value = device;
    uploads.value = page.items;
  } catch (err) {
    error.value = String(err);
  }
});
</script>

<template>
  <div class="health">
    <h2>Device health</h2>
    <el-alert v-if="error" :title="error" type="error" show-icon :closable="false" />
    <div class="health__charts">
      <EChart :option="diskOption" />
      <EChart :option="queueOption" />
    </div>
    <el-table :data="status ? [status] : []">
      <el-table-column prop="operational_state" label="State" width="140" />
      <el-table-column prop="inspection_ready" label="Inspection ready" width="140">
        <template #default="{ row }">{{ row.inspection_ready ? "yes" : "no" }}</template>
      </el-table-column>
      <el-table-column prop="camera_connected" label="Camera" width="100">
        <template #default="{ row }">{{ row.camera_connected ? "connected" : "disconnected" }}</template>
      </el-table-column>
      <el-table-column prop="model_loaded" label="Model" width="100">
        <template #default="{ row }">{{ row.model_loaded ? "loaded" : "missing" }}</template>
      </el-table-column>
      <el-table-column prop="central_connected" label="Central" width="100">
        <template #default="{ row }">{{ row.central_connected ? "connected" : "offline" }}</template>
      </el-table-column>
      <el-table-column label="Free disk" width="140">
        <template #default="{ row }">{{ formatBytes(row.disk_free_bytes) }}</template>
      </el-table-column>
      <el-table-column prop="upload_pending_count" label="Pending uploads" width="140" />
    </el-table>
  </div>
</template>

<style scoped>
.health {
  padding: 16px;
  display: flex;
  flex-direction: column;
  gap: 16px;
}
.health__charts {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 16px;
}
</style>

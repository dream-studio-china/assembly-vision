<script setup lang="ts">
import { formatBytes, formatIsoTime } from "@assemblyvision/ui";
import * as echarts from "echarts";
import { computed, onMounted, ref } from "vue";
import EChart from "../components/EChart.vue";
import { getApiClient } from "../services/client";
import { useAlertsStore } from "../stores/alerts";
import type { Alert } from "../stores/alerts";
import { chartTokens } from "../theme";
import type { DeviceStatus, UploadTask } from "@assemblyvision/api-client";

const status = ref<DeviceStatus | null>(null);
const uploads = ref<UploadTask[]>([]);
const error = ref<string | null>(null);
const lastUpdated = ref<string | null>(null);

const alertsStore = useAlertsStore();
const activeAlerts = computed<Alert[]>(() => alertsStore.alerts);
const clearedAlerts = computed<Alert[]>(() => alertsStore.history);

const severityLabel: Record<Alert["severity"], string> = {
  critical: "Critical",
  warning: "Warning",
  info: "Info",
};

function severityLabelOf(severity: string): string {
  return severityLabel[severity as Alert["severity"]] ?? severity;
}

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
    lastUpdated.value = new Date().toISOString();
    alertsStore.setFromDeviceStatus(device);
  } catch (err) {
    error.value = String(err);
  }
});
</script>

<template>
  <div class="health">
    <h2>Device health</h2>
    <el-alert v-if="error" :title="error" type="error" show-icon :closable="false" />
    <p v-if="lastUpdated" class="health__updated">Last updated {{ formatIsoTime(lastUpdated) }}</p>

    <section v-if="activeAlerts.length > 0" class="health__alerts">
      <h3>Active alerts</h3>
      <el-table :data="activeAlerts">
        <el-table-column label="Severity" width="110">
          <template #default="{ row }">
            <span class="severity-chip" :class="`severity-chip--${row.severity}`">{{ severityLabelOf(row.severity) }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="code" label="Code" width="180" />
        <el-table-column prop="message" label="Message" min-width="200" />
        <el-table-column label="Guidance" min-width="280">
          <template #default="{ row }">
            <span class="health__guidance">{{ row.guidance }}</span>
          </template>
        </el-table-column>
        <el-table-column label="First observed" width="180">
          <template #default="{ row }">{{ formatIsoTime(row.firstSeenAt) }}</template>
        </el-table-column>
        <el-table-column label="Last observed" width="180">
          <template #default="{ row }">{{ formatIsoTime(row.lastSeenAt) }}</template>
        </el-table-column>
        <el-table-column v-if="activeAlerts.some((a) => a.severity !== 'critical')" label="" width="110">
          <template #default="{ row }">
            <el-button v-if="row.severity !== 'critical'" size="small" text type="primary" @click="alertsStore.dismiss(row.id)">
              Dismiss
            </el-button>
          </template>
        </el-table-column>
      </el-table>
    </section>

    <section v-if="clearedAlerts.length > 0" class="health__cleared">
      <el-collapse>
        <el-collapse-item :title="`Cleared alerts (${clearedAlerts.length})`" name="cleared">
          <el-table :data="clearedAlerts">
            <el-table-column label="Severity" width="110">
              <template #default="{ row }">
                <span class="severity-chip" :class="`severity-chip--${row.severity}`">{{ severityLabelOf(row.severity) }}</span>
              </template>
            </el-table-column>
            <el-table-column prop="code" label="Code" width="180" />
            <el-table-column prop="message" label="Message" min-width="200" />
            <el-table-column label="Guidance" min-width="280">
              <template #default="{ row }">
                <span class="health__guidance">{{ row.guidance }}</span>
              </template>
            </el-table-column>
            <el-table-column label="First observed" width="180">
              <template #default="{ row }">{{ formatIsoTime(row.firstSeenAt) }}</template>
            </el-table-column>
            <el-table-column label="Cleared" width="180">
              <template #default="{ row }">{{ formatIsoTime(row.clearedAt) }}</template>
            </el-table-column>
          </el-table>
        </el-collapse-item>
      </el-collapse>
    </section>

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
.health__updated {
  margin: 0;
  color: var(--text-muted);
  font-size: 12px;
}
.health__guidance {
  color: var(--text-muted);
  font-size: 13px;
}
.severity-chip {
  display: inline-block;
  border-radius: var(--radius-small);
  padding: 2px 10px;
  font-size: 12px;
  font-weight: 600;
}
.severity-chip--critical {
  background: var(--status-ng-soft);
  color: var(--status-ng);
}
.severity-chip--warning {
  background: var(--status-warning-soft);
  color: var(--status-warning);
}
.severity-chip--info {
  background: var(--status-info-soft);
  color: var(--status-info);
}
.health__charts {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 16px;
}
</style>

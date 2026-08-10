<script setup lang="ts">
import { formatBytes, formatIsoTime } from "@assemblyvision/ui";
import * as echarts from "echarts";
import { computed, onBeforeUnmount, onMounted, ref } from "vue";
import { useI18n } from "vue-i18n";
import EChart from "../components/EChart.vue";
import { getApiClient } from "../services/client";
import { useAlertsStore } from "../stores/alerts";
import type { Alert } from "../stores/alerts";
import { chartTokens } from "../theme";
import type { DeviceStatus, UploadTask } from "@assemblyvision/api-client";

const { t } = useI18n();
const status = ref<DeviceStatus | null>(null);
const uploads = ref<UploadTask[]>([]);
const error = ref<string | null>(null);
const lastUpdated = ref<string | null>(null);
let pollTimer: ReturnType<typeof setInterval> | null = null;

const alertsStore = useAlertsStore();
const activeAlerts = computed<Alert[]>(() => alertsStore.alerts);
const clearedAlerts = computed<Alert[]>(() => alertsStore.history);

const severityLabel: Record<Alert["severity"], string> = {
  critical: t("Critical"),
  warning: t("Warning"),
  info: t("Info"),
};

function severityLabelOf(severity: string): string {
  return severityLabel[severity as Alert["severity"]] ?? severity;
}

// Host resource gauges (design 15.3.1): load as a share of the CPU cores,
// memory and disk as used/total percentages. Null means the platform cannot
// measure the value, so the gauge renders empty with a "-" caption.
const loadPercent = computed<number | null>(() => {
  const load = status.value?.load_1m;
  const cores = status.value?.cpu_count;
  if (load === null || load === undefined || cores === null || cores === undefined || cores <= 0) {
    return null;
  }
  return Math.min(100, Math.round((load / cores) * 100));
});

const memoryUsed = computed<number>(() => {
  const total = status.value?.memory_total_bytes ?? 0;
  const available = status.value?.memory_available_bytes ?? 0;
  return Math.max(0, total - available);
});

const memoryPercent = computed<number | null>(() => {
  const total = status.value?.memory_total_bytes ?? 0;
  if (total <= 0) return null;
  return Math.round((memoryUsed.value / total) * 100);
});

const diskUsed = computed<number>(() => {
  const total = status.value?.storage_total_bytes ?? 0;
  const free = status.value?.storage_free_bytes ?? status.value?.disk_free_bytes ?? 0;
  return Math.max(0, total - free);
});

const diskPercent = computed<number | null>(() => {
  const total = status.value?.storage_total_bytes ?? 0;
  if (total <= 0) return null;
  return Math.round((diskUsed.value / total) * 100);
});

function gaugeColor(percent: number): string {
  if (percent >= 85) return "var(--status-ng)";
  if (percent >= 70) return "var(--status-warning)";
  return "var(--status-ok)";
}

// GPU gauges: utilization is already a percentage; power is shown as a share
// of the card power limit. Null means no NVIDIA GPU is present.
const gpuLoadPercent = computed<number | null>(() => {
  const value = status.value?.gpu_utilization_percent;
  if (value === null || value === undefined) return null;
  return Math.min(100, Math.round(value));
});

const gpuPowerPercent = computed<number | null>(() => {
  const watts = status.value?.gpu_power_watts;
  const max = status.value?.gpu_power_max_watts;
  if (watts === null || watts === undefined || max === null || max === undefined || max <= 0) {
    return null;
  }
  return Math.min(100, Math.round((watts / max) * 100));
});

const gpuPowerCaption = computed<string>(() => {
  const watts = status.value?.gpu_power_watts;
  const max = status.value?.gpu_power_max_watts;
  if (watts === null || watts === undefined || max === null || max === undefined) return "-";
  return `${Math.round(watts)} W / ${Math.round(max)} W`;
});

// Live network traffic: one sample per second, sliding window of 60 points.
type NetPoint = { time: string; rx: number; tx: number };
const NET_WINDOW = 60;
const netSeries = ref<NetPoint[]>([]);

function pushNetPoint(): void {
  const rx = status.value?.network_rx_bytes_per_sec;
  const tx = status.value?.network_tx_bytes_per_sec;
  netSeries.value = [
    ...netSeries.value.slice(-(NET_WINDOW - 1)),
    {
      time: new Date().toLocaleTimeString(),
      rx: rx === null || rx === undefined ? 0 : rx,
      tx: tx === null || tx === undefined ? 0 : tx,
    },
  ];
}

const networkOption = computed<echarts.EChartsOption>(() => {
  const theme = chartTokens();
  const rxColor = theme.accent;
  const txColor = theme.ok;
  return {
    title: { text: t("Network traffic"), left: "center", textStyle: { fontSize: 14, color: theme.text } },
    tooltip: { trigger: "axis", backgroundColor: "var(--surface-raised)", borderColor: "var(--border)", textStyle: { color: "var(--text)" } },
    legend: { data: [t("Download"), t("Upload")], top: 28, textStyle: { color: theme.text, fontSize: 11 } },
    grid: { top: 56, left: 8, right: 8, bottom: 8, containLabel: true },
    xAxis: {
      type: "category",
      data: netSeries.value.map((p) => p.time),
      boundaryGap: false,
      axisLine: { lineStyle: { color: theme.border } },
      axisLabel: { color: theme.text, fontSize: 9, interval: 10 },
    },
    yAxis: {
      type: "value",
      splitLine: { lineStyle: { color: theme.border } },
      axisLabel: { color: theme.text, fontSize: 9, formatter: (value: number) => `${formatBytes(value)}/s` },
    },
    series: [
      {
        name: t("Download"),
        type: "line",
        stack: "traffic",
        smooth: true,
        showSymbol: false,
        data: netSeries.value.map((p) => p.rx),
        lineStyle: { width: 1.5, color: rxColor },
        itemStyle: { color: rxColor },
        areaStyle: {
          color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
            { offset: 0, color: echarts.color.modifyAlpha(rxColor, 0.35) },
            { offset: 1, color: echarts.color.modifyAlpha(rxColor, 0.02) },
          ]),
        },
      },
      {
        name: t("Upload"),
        type: "line",
        stack: "traffic",
        smooth: true,
        showSymbol: false,
        data: netSeries.value.map((p) => p.tx),
        lineStyle: { width: 1.5, color: txColor },
        itemStyle: { color: txColor },
        areaStyle: {
          color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
            { offset: 0, color: echarts.color.modifyAlpha(txColor, 0.35) },
            { offset: 1, color: echarts.color.modifyAlpha(txColor, 0.02) },
          ]),
        },
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
    title: { text: t("Upload queue by state"), left: "center", textStyle: { fontSize: 14, color: theme.text } },
    grid: { top: 52, left: 8, right: 8, bottom: 8, containLabel: true },
    xAxis: {
      type: "category",
      data: Object.keys(byState),
      axisLine: { lineStyle: { color: theme.border } },
      axisLabel: { color: theme.text, fontSize: 10, rotate: 30 },
    },
    yAxis: { type: "value", minInterval: 1, splitLine: { lineStyle: { color: theme.border } }, axisLabel: { color: theme.text, fontSize: 10 } },
    series: [{ type: "bar", data: Object.values(byState), itemStyle: { color: theme.accent }, barMaxWidth: 24 }],
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
    pushNetPoint();
  } catch (err) {
    error.value = String(err);
  }
  // The network area chart samples once per second; the gauges refresh with
  // the same poll since they share the device status snapshot.
  pollTimer = setInterval(async () => {
    try {
      status.value = await getApiClient().getDeviceStatus();
      lastUpdated.value = new Date().toISOString();
      pushNetPoint();
    } catch {
      // keep the last known snapshot; the stale timestamp marks it
    }
  }, 1000);
});

onBeforeUnmount(() => {
  if (pollTimer !== null) clearInterval(pollTimer);
});
</script>

<template>
  <div class="health">
    <h2>{{ t("Device health") }}</h2>
    <el-alert v-if="error" :title="error" type="error" show-icon :closable="false" />
    <p v-if="lastUpdated" class="health__updated">{{ t("Last updated {time}", { time: formatIsoTime(lastUpdated) }) }}</p>

    <section v-if="activeAlerts.length > 0" class="health__alerts">
      <h3>{{ t("Active alerts") }}</h3>
      <el-table :data="activeAlerts">
        <el-table-column :label="t('Severity')" width="110">
          <template #default="{ row }">
            <span class="severity-chip" :class="`severity-chip--${row.severity}`">{{ severityLabelOf(row.severity) }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="code" :label="t('Code')" width="180" />
        <el-table-column prop="message" :label="t('Message')" min-width="200" />
        <el-table-column :label="t('Guidance')" min-width="280">
          <template #default="{ row }">
            <span class="health__guidance">{{ row.guidance }}</span>
          </template>
        </el-table-column>
        <el-table-column :label="t('First observed')" width="180">
          <template #default="{ row }">{{ formatIsoTime(row.firstSeenAt) }}</template>
        </el-table-column>
        <el-table-column :label="t('Last observed')" width="180">
          <template #default="{ row }">{{ formatIsoTime(row.lastSeenAt) }}</template>
        </el-table-column>
        <el-table-column v-if="activeAlerts.some((a) => a.severity !== 'critical')" label="" width="110">
          <template #default="{ row }">
            <el-button v-if="row.severity !== 'critical'" size="small" text type="primary" @click="alertsStore.dismiss(row.id)">
              {{ t("Dismiss") }}
            </el-button>
          </template>
        </el-table-column>
      </el-table>
    </section>

    <section v-if="clearedAlerts.length > 0" class="health__cleared">
      <el-collapse>
        <el-collapse-item :title="t('Cleared alerts ({count})', { count: clearedAlerts.length })" name="cleared">
          <el-table :data="clearedAlerts">
            <el-table-column :label="t('Severity')" width="110">
              <template #default="{ row }">
                <span class="severity-chip" :class="`severity-chip--${row.severity}`">{{ severityLabelOf(row.severity) }}</span>
              </template>
            </el-table-column>
            <el-table-column prop="code" :label="t('Code')" width="180" />
            <el-table-column prop="message" :label="t('Message')" min-width="200" />
            <el-table-column :label="t('Guidance')" min-width="280">
              <template #default="{ row }">
                <span class="health__guidance">{{ row.guidance }}</span>
              </template>
            </el-table-column>
            <el-table-column :label="t('First observed')" width="180">
              <template #default="{ row }">{{ formatIsoTime(row.firstSeenAt) }}</template>
            </el-table-column>
            <el-table-column :label="t('Cleared')" width="180">
              <template #default="{ row }">{{ formatIsoTime(row.clearedAt) }}</template>
            </el-table-column>
          </el-table>
        </el-collapse-item>
      </el-collapse>
    </section>

    <div class="health__row health__row--system">
      <div class="gauge">
        <el-progress
          type="circle"
          :percentage="loadPercent ?? 0"
          :width="120"
          :stroke-width="10"
          :color="gaugeColor(loadPercent ?? 0)"
        />
        <div class="gauge__label">{{ t("Load") }}</div>
        <div class="gauge__sub">{{ t("CPU {count} cores total load", { count: status?.cpu_count ?? "-" }) }}</div>
      </div>
      <div class="gauge">
        <el-progress
          type="circle"
          :percentage="memoryPercent ?? 0"
          :width="120"
          :stroke-width="10"
          :color="gaugeColor(memoryPercent ?? 0)"
        />
        <div class="gauge__label">{{ t("Memory") }}</div>
        <div class="gauge__sub">{{ formatBytes(memoryUsed) }} / {{ formatBytes(status?.memory_total_bytes ?? 0) }}</div>
      </div>
      <div class="gauge">
        <el-progress
          type="circle"
          :percentage="gpuLoadPercent ?? 0"
          :width="120"
          :stroke-width="10"
          :color="gaugeColor(gpuLoadPercent ?? 0)"
        />
        <div class="gauge__label">{{ t("GPU load") }}</div>
        <div class="gauge__sub">{{ gpuLoadPercent === null ? "-" : `${gpuLoadPercent}%` }}</div>
      </div>
      <div class="gauge">
        <el-progress
          type="circle"
          :percentage="gpuPowerPercent ?? 0"
          :width="120"
          :stroke-width="10"
          :color="gaugeColor(gpuPowerPercent ?? 0)"
        />
        <div class="gauge__label">{{ t("GPU power") }}</div>
        <div class="gauge__sub">{{ gpuPowerCaption }}</div>
      </div>
    </div>

    <div class="health__row health__row--network">
      <div class="health__network">
        <EChart :option="networkOption" />
      </div>
      <div class="gauge">
        <el-progress
          type="circle"
          :percentage="diskPercent ?? 0"
          :width="120"
          :stroke-width="10"
          :color="gaugeColor(diskPercent ?? 0)"
        />
        <div class="gauge__label">{{ t("Disk") }}</div>
        <div class="gauge__sub">{{ formatBytes(diskUsed) }} / {{ formatBytes(status?.storage_total_bytes ?? 0) }}</div>
      </div>
      <div class="health__queue">
        <EChart :option="queueOption" />
      </div>
    </div>

    <el-table :data="status ? [status] : []">
      <el-table-column prop="operational_state" :label="t('State')" width="140" />
      <el-table-column prop="inspection_ready" :label="t('Inspection ready')" width="140">
        <template #default="{ row }">{{ row.inspection_ready ? t("yes") : t("no") }}</template>
      </el-table-column>
      <el-table-column prop="camera_connected" :label="t('Camera')" width="100">
        <template #default="{ row }">{{ row.camera_connected ? t("connected") : t("disconnected") }}</template>
      </el-table-column>
      <el-table-column prop="model_loaded" :label="t('Model')" width="100">
        <template #default="{ row }">{{ row.model_loaded ? t("loaded") : t("missing") }}</template>
      </el-table-column>
      <el-table-column prop="central_connected" :label="t('Central')" width="100">
        <template #default="{ row }">{{ row.central_connected ? t("connected") : t("offline") }}</template>
      </el-table-column>
      <el-table-column :label="t('Free disk')" width="140">
        <template #default="{ row }">{{ formatBytes(row.disk_free_bytes) }}</template>
      </el-table-column>
      <el-table-column prop="upload_pending_count" :label="t('Pending uploads')" width="140" />
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
.health__row {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 16px;
}
/* ECharts canvases carry their own intrinsic width, which would otherwise
   become the grid item's min-width and stop the row from shrinking with the
   window; 0 lets the grid compress and the ResizeObserver redraw the chart. */
.health__row > * {
  min-width: 0;
}
.gauge {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 6px;
  text-align: center;
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: var(--panel-padding);
  background: var(--surface-raised);
  box-shadow: var(--shadow);
}
.gauge__label {
  font-weight: 600;
  font-size: 13px;
}
.gauge__sub {
  color: var(--text-muted);
  font-size: 12px;
}
.health__network {
  grid-column: span 2;
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: var(--panel-padding);
  background: var(--surface-raised);
  box-shadow: var(--shadow);
}
.health__network :deep(.echart) {
  height: 180px;
}
.health__queue {
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: var(--panel-padding);
  background: var(--surface-raised);
  box-shadow: var(--shadow);
}
.health__queue :deep(.echart) {
  height: 180px;
}
</style>

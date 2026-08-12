<script setup lang="ts">
import { onMounted, onUnmounted, reactive, ref, watch } from "vue";
import { useI18n } from "vue-i18n";

import {
  apiClient,
  type DashboardQuery,
  type DashboardSummary,
  type DashboardTimeseries,
  type DeviceStatus,
  type Line,
  type Site,
} from "@assemblyvision/api-client-central";
import * as echarts from "echarts";

import { formatMillis, formatNumber } from "../lib/format";

const { t, locale } = useI18n();
const summary = ref<DashboardSummary | null>(null);
const timeseries = ref<DashboardTimeseries | null>(null);
const devices = ref<DeviceStatus[]>([]);
const sites = ref<Site[]>([]);
const lines = ref<Line[]>([]);
const error = ref<string | null>(null);

const scope = reactive<DashboardQuery>({
  site_id: undefined,
  line_id: undefined,
  from_at: undefined,
  to_at: undefined,
});

const chartEl = ref<HTMLElement | null>(null);
let chart: echarts.ECharts | null = null;

async function load(): Promise<void> {
  error.value = null;
  try {
    const params: DashboardQuery = {
      site_id: scope.site_id,
      line_id: scope.line_id,
      from_at: scope.from_at,
      to_at: scope.to_at,
    };
    [summary.value, timeseries.value, devices.value] = await Promise.all([
      apiClient.getDashboardSummary(params),
      apiClient.getDashboardTimeseries(params),
      apiClient.getDashboardDevices(),
    ]);
    renderChart();
  } catch (err) {
    error.value = err instanceof Error ? err.message : t("failed to load the dashboard");
  }
}

function renderChart(): void {
  if (!chartEl.value) {
    return;
  }
  chart ??= echarts.init(chartEl.value);
  const points = timeseries.value?.points ?? [];
  const ok = t("OK");
  const ng = t("NG");
  const uncertain = t("Uncertain");
  chart.setOption({
    tooltip: { trigger: "axis" },
    legend: { data: [ok, ng, uncertain] },
    grid: { left: 40, right: 20, top: 40, bottom: 40 },
    xAxis: { type: "category", data: points.map((p) => p.bucket) },
    yAxis: {
      type: "value",
      minInterval: 1,
      axisLabel: { formatter: (value: number) => value.toLocaleString(locale.value) },
    },
    series: [
      { name: ok, type: "bar", stack: "outcome", data: points.map((p) => p.ok_count) },
      { name: ng, type: "bar", stack: "outcome", data: points.map((p) => p.ng_count) },
      {
        name: uncertain,
        type: "bar",
        stack: "outcome",
        data: points.map((p) => p.uncertain_count),
      },
    ],
  });
}

function resize(): void {
  chart?.resize();
}

watch(scope, () => load());
onMounted(() => {
  load();
  apiClient
    .listSites()
    .then((s) => (sites.value = s))
    .catch(() => undefined);
  window.addEventListener("resize", resize);
});
onUnmounted(() => {
  window.removeEventListener("resize", resize);
  chart?.dispose();
});

async function onSiteChange(siteId?: number): Promise<void> {
  scope.line_id = undefined;
  lines.value = siteId ? await apiClient.listLines(siteId) : [];
}
</script>

<template>
  <main class="overview">
    <header>
      <h1>{{ t("Overview") }}</h1>
      <p class="muted">
        {{ t("Counts are sample denominators for the selected scope, not accuracy claims.") }}
      </p>
    </header>

    <el-card class="block">
      <div class="filters">
        <el-select v-model="scope.site_id" :placeholder="t('Site')" clearable class="filter" @change="onSiteChange">
          <el-option v-for="site in sites" :key="site.id" :label="site.name" :value="site.id" />
        </el-select>
        <el-select v-model="scope.line_id" :placeholder="t('Line')" clearable class="filter">
          <el-option v-for="line in lines" :key="line.id" :label="line.name" :value="line.id" />
        </el-select>
        <el-date-picker
          v-model="scope.from_at"
          type="date"
          :placeholder="t('From (UTC)')"
          value-format="YYYY-MM-DDT00:00:00.000Z"
          class="filter"
        />
        <el-date-picker
          v-model="scope.to_at"
          type="date"
          :placeholder="t('To (UTC)')"
          value-format="YYYY-MM-DDT00:00:00.000Z"
          class="filter"
        />
      </div>
    </el-card>

    <el-alert v-if="error" :title="error" type="error" show-icon class="block" />

    <section v-if="summary" class="cards">
      <el-card class="metric">
        <div class="metric-value">{{ formatNumber(summary.inspection_count, locale) }}</div>
        <div class="metric-label">{{ t("Inspections") }}</div>
      </el-card>
      <el-card class="metric ok">
        <div class="metric-value">{{ formatNumber(summary.ok_count, locale) }}</div>
        <div class="metric-label">{{ t("OK") }}</div>
      </el-card>
      <el-card class="metric ng">
        <div class="metric-value">{{ formatNumber(summary.ng_count, locale) }}</div>
        <div class="metric-label">{{ t("NG") }}</div>
      </el-card>
      <el-card class="metric uncertain">
        <div class="metric-value">{{ formatNumber(summary.uncertain_count, locale) }}</div>
        <div class="metric-label">{{ t("Uncertain") }}</div>
      </el-card>
      <el-card class="metric">
        <div class="metric-value">
          {{ formatMillis(summary.avg_upload_delay_ms, locale) }}
        </div>
        <div class="metric-label">{{ t("Mean upload delay") }}</div>
      </el-card>
    </section>

    <el-card class="block">
      <template #header>{{ t("Daily outcomes") }}</template>
      <div ref="chartEl" class="chart" />
    </el-card>

    <el-card class="block">
      <template #header>{{ t("Devices") }}</template>
      <el-table :data="devices" :empty-text="t('No registered devices.')">
        <el-table-column prop="device_id" :label="t('Device id')" width="260" show-overflow-tooltip />
        <el-table-column prop="name" :label="t('Name')" width="160" />
        <el-table-column :label="t('Last seen (UTC)')" width="220">
          <template #default="{ row }">
            {{ row.last_seen_at ? new Date(row.last_seen_at).toLocaleString() : "–" }}
          </template>
        </el-table-column>
        <el-table-column prop="inspection_count" :label="t('Inspections')" width="120">
          <template #default="{ row }">{{ formatNumber(row.inspection_count, locale) }}</template>
        </el-table-column>
      </el-table>
    </el-card>
  </main>
</template>

<style scoped>
.overview {
  max-width: 1100px;
  margin: 0 auto;
  padding: 1rem;
}

.block {
  margin-top: 0.75rem;
}

.filters {
  display: flex;
  gap: 0.5rem;
  flex-wrap: wrap;
}

.filter {
  width: 180px;
}

.cards {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
  gap: 0.5rem;
  margin-top: 0.75rem;
}

.metric-value {
  font-size: 1.35rem;
  font-weight: 600;
}

.metric-label {
  color: var(--text-muted);
  font-size: 0.8rem;
}

.metric.ok .metric-value {
  color: var(--status-ok);
}

.metric.ng .metric-value {
  color: var(--status-ng);
}

.metric.uncertain .metric-value {
  color: var(--status-warning);
}

.chart {
  height: 280px;
}

.muted {
  color: var(--text-muted);
}
</style>

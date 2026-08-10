<script setup lang="ts">
// Production statistics: totals, pass/NG counts, pass rate, with date and
// production-line filters.

import * as echarts from "echarts";
import { computed, onMounted, ref } from "vue";
import EChart from "../components/EChart.vue";
import { inspectionService } from "../services/inspectionService";
import { chartTokens } from "../theme";
import type { StatisticsSummary } from "@assemblyvision/api-client";

const stats = ref<StatisticsSummary | null>(null);
const from = ref<string>("");
const to = ref<string>("");
const line = ref<string>("");

const pieOption = computed<echarts.EChartsOption>(() => {
  const theme = chartTokens();
  return {
  title: { text: "Result split", left: "center", textStyle: { fontSize: 14, color: theme.text } },
  tooltip: { trigger: "item" },
  series: [
    {
      type: "pie",
      radius: ["40%", "70%"],
      data: [
        { name: "PASS", value: stats.value?.pass_count ?? 0, itemStyle: { color: theme.ok } },
        { name: "NG", value: stats.value?.ng_count ?? 0, itemStyle: { color: theme.ng } },
      ],
    },
  ],
};
});

async function load(): Promise<void> {
  const filter = {
    ...(from.value ? { from: new Date(from.value).toISOString() } : {}),
    ...(to.value ? { to: new Date(to.value + "T23:59:59").toISOString() } : {}),
    ...(line.value ? { line: line.value } : {}),
  };
  stats.value = await inspectionService.getStatistics(filter);
}

onMounted(load);
</script>

<template>
  <div class="stats">
    <h2>Production statistics</h2>

    <div class="stats__filters">
      <el-date-picker v-model="from" type="date" placeholder="From" style="width: 160px" />
      <el-date-picker v-model="to" type="date" placeholder="To" style="width: 160px" />
      <el-select v-model="line" placeholder="All lines" clearable style="width: 160px">
        <el-option label="LINE-1" value="LINE-1" />
      </el-select>
      <el-button type="primary" @click="load">Apply</el-button>
    </div>

    <div class="stats__cards">
      <div class="card"><div class="card__value">{{ stats?.total_inspections ?? "-" }}</div><div class="card__label">Total inspections</div></div>
      <div class="card card--pass"><div class="card__value">{{ stats?.pass_count ?? "-" }}</div><div class="card__label">PASS count</div></div>
      <div class="card card--ng"><div class="card__value">{{ stats?.ng_count ?? "-" }}</div><div class="card__label">NG count</div></div>
      <div class="card"><div class="card__value">{{ stats ? (stats.pass_rate * 100).toFixed(1) + "%" : "-" }}</div><div class="card__label">Pass rate</div></div>
    </div>

    <EChart :option="pieOption" />
  </div>
</template>

<style scoped>
.stats {
  display: flex;
  flex-direction: column;
  gap: 16px;
}
.stats__filters {
  display: flex;
  gap: 12px;
  align-items: center;
}
.stats__cards {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 16px;
}
.card {
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: var(--panel-padding);
  background: var(--surface-raised);
  box-shadow: var(--shadow);
  text-align: center;
}
.card__value {
  font-size: 28px;
  font-weight: 700;
}
.card--pass .card__value {
  color: var(--status-ok);
}
.card--ng .card__value {
  color: var(--status-ng);
}
.card__label {
  color: var(--text-muted);
  font-size: 13px;
  margin-top: 4px;
}
</style>

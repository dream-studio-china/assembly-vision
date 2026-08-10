<script setup lang="ts">
// Production statistics: totals, pass/NG counts, pass rate, plus the
// confidence-drift analysis (design 15.3.6) that compares today's weighted
// mean detection confidence with yesterday and the previous 7 days.

import * as echarts from "echarts";
import { computed, onMounted, ref } from "vue";
import { useI18n } from "vue-i18n";
import EChart from "../components/EChart.vue";
import { inspectionService } from "../services/inspectionService";
import { chartTokens } from "../theme";
import type { ConfidenceDriftReport, DriftLevel, StatisticsSummary } from "@assemblyvision/api-client";

const { t } = useI18n();
const stats = ref<StatisticsSummary | null>(null);
const drift = ref<ConfidenceDriftReport | null>(null);
const driftError = ref<string | null>(null);
const from = ref<string>("");
const to = ref<string>("");
const line = ref<string>("");

const pieOption = computed<echarts.EChartsOption>(() => {
  const theme = chartTokens();
  return {
  title: { text: t("Result split"), left: "center", textStyle: { fontSize: 14, color: theme.text } },
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

const levelLabel = computed<Record<DriftLevel, string>>(() => ({
  stable: t("Stable"),
  minor_drop: t("Minor drop"),
  noticeable_drop: t("Noticeable drop"),
  minor_rise: t("Minor rise"),
  noticeable_rise: t("Noticeable rise"),
  insufficient_data: t("Insufficient data"),
}));

const levelClass = computed<string>(() => {
  const level = drift.value?.assessment.level;
  if (level === "noticeable_drop") return "level--drop";
  if (level === "minor_drop") return "level--drop-soft";
  if (level === "noticeable_rise" || level === "minor_rise") return "level--rise";
  return "level--neutral";
});

function formatPercent(value: number | null): string {
  if (value === null) return "-";
  const sign = value > 0 ? "+" : "";
  return `${sign}${value.toFixed(1)}%`;
}

function formatConfidence(value: number | null): string {
  return value === null ? "-" : (value * 100).toFixed(1) + "%";
}

async function load(): Promise<void> {
  const filter = {
    ...(from.value ? { from: new Date(from.value).toISOString() } : {}),
    ...(to.value ? { to: new Date(to.value + "T23:59:59").toISOString() } : {}),
    ...(line.value ? { line: line.value } : {}),
  };
  stats.value = await inspectionService.getStatistics(filter);
  try {
    drift.value = await inspectionService.getConfidenceDrift();
    driftError.value = null;
  } catch (error) {
    drift.value = null;
    driftError.value = error instanceof Error ? error.message : String(error);
  }
}

onMounted(load);
</script>

<template>
  <div class="stats">
    <h2>{{ t("Production statistics") }}</h2>

    <div class="stats__filters">
      <el-date-picker v-model="from" type="date" :placeholder="t('From')" style="width: 160px" />
      <el-date-picker v-model="to" type="date" :placeholder="t('To')" style="width: 160px" />
      <el-select v-model="line" :placeholder="t('All lines')" clearable style="width: 160px">
        <el-option label="LINE-1" value="LINE-1" />
      </el-select>
      <el-button type="primary" @click="load">{{ t("Apply") }}</el-button>
    </div>

    <div class="stats__cards">
      <div class="card"><div class="card__value">{{ stats?.total_inspections ?? "-" }}</div><div class="card__label">{{ t("Total inspections") }}</div></div>
      <div class="card card--pass"><div class="card__value">{{ stats?.pass_count ?? "-" }}</div><div class="card__label">{{ t("PASS count") }}</div></div>
      <div class="card card--ng"><div class="card__value">{{ stats?.ng_count ?? "-" }}</div><div class="card__label">{{ t("NG count") }}</div></div>
      <div class="card"><div class="card__value">{{ stats ? (stats.pass_rate * 100).toFixed(1) + "%" : "-" }}</div><div class="card__label">{{ t("Pass rate") }}</div></div>
    </div>

    <EChart :option="pieOption" />

    <h2>{{ t("Confidence drift") }}</h2>
    <p class="muted">
      {{ t("Compares today's weighted mean detection confidence with yesterday and the previous 7 days for the same product and rule. A persistent drop can indicate an acquisition-environment change (conveyor, camera focus/angle, lighting).") }}
    </p>

    <template v-if="drift">
      <div class="drift__assessment" :class="levelClass">
        <span class="drift__level">{{ levelLabel[drift.assessment.level] }}</span>
        <span class="drift__detail">{{ drift.assessment.detail }}</span>
      </div>

      <div class="drift__periods">
        <div class="card">
          <div class="card__label">{{ t("Today") }}</div>
          <div class="card__value">{{ formatConfidence(drift.periods.today.weighted_mean) }}</div>
          <div class="card__sub">{{ t("Median") }}: {{ formatConfidence(drift.periods.today.median) }}</div>
          <div class="card__sub">{{ t("Samples") }}: {{ drift.periods.today.evidence_count }}</div>
        </div>
        <div class="card">
          <div class="card__label">{{ t("Yesterday") }}</div>
          <div class="card__value">{{ formatConfidence(drift.periods.yesterday.weighted_mean) }}</div>
          <div class="card__sub">{{ t("Median") }}: {{ formatConfidence(drift.periods.yesterday.median) }}</div>
          <div class="card__sub">{{ t("Samples") }}: {{ drift.periods.yesterday.evidence_count }}</div>
        </div>
        <div class="card">
          <div class="card__label">{{ t("Previous 7 days") }}</div>
          <div class="card__value">{{ formatConfidence(drift.periods.previous_7d.weighted_mean) }}</div>
          <div class="card__sub">{{ t("Median") }}: {{ formatConfidence(drift.periods.previous_7d.median) }}</div>
          <div class="card__sub">{{ t("Samples") }}: {{ drift.periods.previous_7d.evidence_count }}</div>
        </div>
      </div>

      <div class="drift__comparison">
        <table class="table">
          <thead>
            <tr>
              <th>{{ t("Comparison") }}</th>
              <th>{{ t("Delta") }}</th>
              <th>{{ t("Relative") }}</th>
              <th>{{ t("Samples") }}</th>
            </tr>
          </thead>
          <tbody>
            <tr>
              <td>{{ t("Today vs yesterday") }}</td>
              <td>{{ formatConfidence(drift.comparison.today_vs_yesterday.weighted_mean_delta) }}</td>
              <td>{{ formatPercent(drift.comparison.today_vs_yesterday.weighted_mean_relative_percent) }}</td>
              <td>{{ drift.comparison.today_vs_yesterday.today_evidence_count }} / {{ drift.comparison.today_vs_yesterday.baseline_evidence_count }}</td>
            </tr>
            <tr>
              <td>{{ t("Today vs previous 7 days") }}</td>
              <td>{{ formatConfidence(drift.comparison.today_vs_previous_7d.weighted_mean_delta) }}</td>
              <td>{{ formatPercent(drift.comparison.today_vs_previous_7d.weighted_mean_relative_percent) }}</td>
              <td>{{ drift.comparison.today_vs_previous_7d.today_evidence_count }} / {{ drift.comparison.today_vs_previous_7d.baseline_evidence_count }}</td>
            </tr>
          </tbody>
        </table>
      </div>

      <div class="drift__components">
        <table class="table">
          <thead>
            <tr>
              <th>{{ t("Component") }}</th>
              <th>{{ t("Today mean") }}</th>
              <th>{{ t("Baseline mean") }}</th>
              <th>{{ t("Delta") }}</th>
              <th>{{ t("Samples") }}</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="item in drift.components" :key="item.component_code">
              <td>{{ item.component_code }}</td>
              <td>{{ formatConfidence(item.today_weighted_mean) }}</td>
              <td>{{ formatConfidence(item.baseline_weighted_mean) }}</td>
              <td :class="item.delta !== null && item.delta < 0 ? 'delta--down' : 'delta--up'">
                {{ formatConfidence(item.delta) }}
              </td>
              <td>{{ item.today_evidence_count }} / {{ item.baseline_evidence_count }}</td>
            </tr>
          </tbody>
        </table>
      </div>
    </template>

    <el-alert v-else-if="driftError" type="warning" :title="t('Confidence drift unavailable')" :description="driftError" show-icon :closable="false" />
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
.card__sub {
  color: var(--text-muted);
  font-size: 12px;
  margin-top: 2px;
}
.muted {
  color: var(--text-muted);
  font-size: 13px;
}
.drift__assessment {
  display: flex;
  flex-direction: column;
  gap: 4px;
  padding: 12px 16px;
  border-radius: var(--radius);
  border: 1px solid var(--border);
}
.drift__level {
  font-weight: 700;
}
.drift__detail {
  font-size: 13px;
  color: var(--text-muted);
}
.level--drop {
  background: var(--status-ng-translucent, #fef0f0);
  color: var(--status-ng);
}
.level--drop-soft {
  background: var(--status-ng-translucent, #fef0f0);
  color: var(--status-ng);
}
.level--rise {
  background: var(--status-ok-translucent, #f0f9eb);
  color: var(--status-ok);
}
.level--neutral {
  color: var(--text-muted);
}
.drift__periods {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 16px;
}
.table {
  width: 100%;
  border-collapse: collapse;
}
.table th,
.table td {
  border-bottom: 1px solid var(--border);
  padding: 8px 10px;
  text-align: left;
  font-size: 13px;
}
.table th {
  color: var(--text-muted);
  font-weight: 600;
}
.delta--down {
  color: var(--status-ng);
}
.delta--up {
  color: var(--status-ok);
}
</style>

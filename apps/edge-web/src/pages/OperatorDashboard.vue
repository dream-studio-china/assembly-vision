<script setup lang="ts">
// Production inspection dashboard: the main operator workflow
// (status, product, rules, actions).

import { StatusBadge, formatIsoTime, formatLatency } from "@assemblyvision/ui";
import { ElMessage } from "element-plus";
import { computed, onMounted } from "vue";
import { useInspectionStore } from "../stores/inspection";

const store = useInspectionStore();

const statusLabel = computed(() => store.current?.status ?? "WAITING");

// Map the operator workflow state onto the color-independent StatusBadge.
const badgeStatus = computed(() => {
  const s = statusLabel.value;
  if (s === "PASS") return "OK";
  if (s === "NG") return "NG";
  if (s === "PROCESSING") return "UNCERTAIN";
  return "UNCERTAIN";
});

const isBusy = computed(() => store.loading);

async function confirm(): Promise<void> {
  await store.confirmResult();
  if (store.error) ElMessage.error(store.error);
}

async function next(): Promise<void> {
  await store.continueNext();
  if (store.error) ElMessage.error(store.error);
}

async function manual(): Promise<void> {
  await store.triggerManual();
  if (store.error) ElMessage.error(store.error);
}

onMounted(() => void store.loadCurrent());
</script>

<template>
  <div class="dashboard">
    <section class="dashboard__status panel">
      <div class="dashboard__status-row">
        <span class="dashboard__label">Current status</span>
        <StatusBadge :status="badgeStatus" />
        <span class="dashboard__raw-status">{{ statusLabel }}</span>
      </div>
      <div class="dashboard__meta">
        <dl>
          <dt>Product SN</dt>
          <dd>{{ store.current?.sn ?? "—" }}</dd>
          <dt>Product</dt>
          <dd>{{ store.current?.product_code || "—" }}</dd>
          <dt>Inspection time</dt>
          <dd>{{ formatIsoTime(store.current?.started_at) }}</dd>
          <dt>Duration</dt>
          <dd>{{ formatLatency(store.current?.duration_ms) }}</dd>
          <dt>Operator</dt>
          <dd>{{ store.current?.operator ?? "—" }}</dd>
        </dl>
      </div>
      <div class="dashboard__progress">
        <el-progress
          :percentage="Math.round((store.current?.progress ?? 0) * 100)"
          :stroke-width="12"
        />
      </div>
    </section>

    <section class="panel">
      <h2>Inspection rules</h2>
      <el-table :data="store.current?.rules ?? []" size="large" v-loading="store.loading">
        <el-table-column prop="name" label="Rule" min-width="220" />
        <el-table-column label="Status" width="130">
          <template #default="{ row }">
            <span class="rule" :class="`rule--${row.status.toLowerCase()}`">{{ row.status }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="result_message" label="Result message" min-width="260" />
      </el-table>
    </section>

    <section class="panel dashboard__actions">
      <el-button
        type="success"
        size="large"
        :disabled="statusLabel !== 'PROCESSING' || isBusy"
        :loading="isBusy"
        @click="confirm"
      >
        Confirm result
      </el-button>
      <el-button type="primary" size="large" :loading="isBusy" @click="next">
        Continue next inspection
      </el-button>
      <el-button size="large" :loading="isBusy" @click="manual">
        Trigger manual inspection
      </el-button>
    </section>
  </div>
</template>

<style scoped>
.dashboard {
  display: flex;
  flex-direction: column;
  gap: 16px;
}
.panel {
  border: 1px solid #e0e0e0;
  border-radius: 6px;
  padding: 16px;
}
.dashboard__status-row {
  display: flex;
  align-items: center;
  gap: 12px;
}
.dashboard__label {
  font-weight: 600;
  color: #374151;
}
.dashboard__raw-status {
  font-size: 13px;
  color: #6b7280;
}
.dashboard__meta dl {
  display: grid;
  grid-template-columns: 130px 1fr;
  gap: 6px 16px;
  font-size: 14px;
  margin: 12px 0;
}
.dashboard__meta dt {
  color: #6b7280;
}
.dashboard__meta dd {
  margin: 0;
  font-variant-numeric: tabular-nums;
}
.dashboard__progress {
  margin-top: 8px;
}
.dashboard__actions {
  display: flex;
  gap: 12px;
}
.rule {
  display: inline-block;
  border-radius: 999px;
  padding: 2px 12px;
  font-size: 12px;
}
.rule--pass {
  background: #e8f5e9;
  color: #1b5e20;
}
.rule--ng {
  background: #fdecea;
  color: #b71c1c;
}
.rule--checking {
  background: #fff3e0;
  color: #e65100;
}
.rule--pending {
  background: #eceff1;
  color: #546e7a;
}
</style>

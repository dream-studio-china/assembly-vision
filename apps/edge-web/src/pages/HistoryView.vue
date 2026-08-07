<script setup lang="ts">
// Inspection history: search by SN, filter by result, image reference links.

import { StatusBadge, formatIsoTime, toDecisionStatus } from "@assemblyvision/ui";
import { computed, onMounted, ref } from "vue";
import { inspectionService } from "../services/inspectionService";
import type { InspectionSummary } from "@assemblyvision/api-client";

const items = ref<InspectionSummary[]>([]);
const loading = ref(false);
const snFilter = ref("");
const resultFilter = ref<"" | "OK" | "NG">("");

const filtered = computed(() => {
  let rows = items.value;
  if (snFilter.value.trim()) {
    const q = snFilter.value.trim().toLowerCase();
    rows = rows.filter((r) => (r.sn ?? "").toLowerCase().includes(q));
  }
  if (resultFilter.value) {
    rows = rows.filter((r) => r.business_result === resultFilter.value);
  }
  return rows;
});

async function load(): Promise<void> {
  loading.value = true;
  try {
    const page = await inspectionService.listHistory({ limit: 100 });
    items.value = page.items;
  } finally {
    loading.value = false;
  }
}

onMounted(load);
</script>

<template>
  <div class="history">
    <h2>Inspection history</h2>

    <div class="history__filters">
      <el-input
        v-model="snFilter"
        placeholder="Search by SN"
        clearable
        style="width: 240px"
      />
      <el-select v-model="resultFilter" placeholder="All results" clearable style="width: 160px">
        <el-option label="PASS" value="OK" />
        <el-option label="NG" value="NG" />
      </el-select>
    </div>

    <el-table :data="filtered" v-loading="loading">
      <el-table-column prop="sn" label="SN" width="140">
        <template #default="{ row }">
          <router-link v-if="row.sn" :to="`/traceability/${row.sn}`">{{ row.sn }}</router-link>
          <span v-else>—</span>
        </template>
      </el-table-column>
      <el-table-column prop="completed_at" label="Timestamp" min-width="170">
        <template #default="{ row }">{{ formatIsoTime(row.completed_at) }}</template>
      </el-table-column>
      <el-table-column label="Result" width="110">
        <template #default="{ row }">
          <StatusBadge :status="toDecisionStatus(row.business_result, row.internal_decision)" />
        </template>
      </el-table-column>
      <el-table-column prop="reason_summary" label="Failure reason" min-width="200">
        <template #default="{ row }">
          <span v-if="row.reason_summary.length">{{ row.reason_summary.join(", ") }}</span>
          <span v-else>-</span>
        </template>
      </el-table-column>
      <el-table-column label="Images" width="120">
        <template #default="{ row }">
          <router-link :to="`/images/${row.inspection_id}`">view</router-link>
        </template>
      </el-table-column>
    </el-table>
  </div>
</template>

<style scoped>
.history {
  display: flex;
  flex-direction: column;
  gap: 16px;
}
.history__filters {
  display: flex;
  gap: 12px;
}
</style>

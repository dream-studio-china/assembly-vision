<script setup lang="ts">
import type { InspectionSummary } from "@assemblyvision/api-client";
import { StatusBadge, formatIsoTime, toDecisionStatus } from "@assemblyvision/ui";
import { onMounted, ref } from "vue";
import { getApiClient } from "../services/client";

const items = ref<InspectionSummary[]>([]);
const loading = ref(false);
const filter = ref<{ business_result?: "OK" | "NG" }>({});

async function load(): Promise<void> {
  loading.value = true;
  try {
    const page = await getApiClient().listInspections(filter.value);
    items.value = page.items;
  } finally {
    loading.value = false;
  }
}

onMounted(load);
</script>

<template>
  <div class="inspections">
    <div class="inspections__filters">
      <el-select
        v-model="filter.business_result"
        data-testid="inspection-result-filter"
        aria-label="Inspection result filter"
        placeholder="All results"
        clearable
        @change="load"
        style="width: 180px"
      >
        <el-option label="OK" value="OK" />
        <el-option label="NG" value="NG" />
      </el-select>
    </div>

    <el-table :data="items" v-loading="loading">
      <el-table-column prop="inspection_id" label="Inspection ID" min-width="200">
        <template #default="{ row }">
          <router-link :to="`/inspections/${row.inspection_id}`">{{ row.inspection_id }}</router-link>
        </template>
      </el-table-column>
      <el-table-column label="Result" width="120">
        <template #default="{ row }">
          <StatusBadge :status="toDecisionStatus(row.business_result, row.internal_decision)" />
        </template>
      </el-table-column>
      <el-table-column prop="product_code" label="Product" width="120" />
      <el-table-column prop="completed_at" label="Completed" min-width="170">
        <template #default="{ row }">{{ formatIsoTime(row.completed_at) }}</template>
      </el-table-column>
      <el-table-column prop="reason_summary" label="Reasons" min-width="200">
        <template #default="{ row }">
          <span v-for="code in row.reason_summary" :key="code" class="inspections__reason">{{ code }}</span>
        </template>
      </el-table-column>
      <el-table-column prop="upload_state" label="Upload" width="110" />
    </el-table>
  </div>
</template>

<style scoped>
.inspections {
  padding: 16px;
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.inspections__reason {
  background: var(--status-ng-soft);
  color: var(--status-ng);
  border-radius: var(--radius-small);
  padding: 1px 6px;
  margin-right: 4px;
  font-size: 12px;
}
</style>

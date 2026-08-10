<script setup lang="ts">
import type { InspectionFilter, InspectionSummary } from "@assemblyvision/api-client";
import { StatusBadge, formatIsoTime, toDecisionStatus } from "@assemblyvision/ui";
import { onMounted, ref } from "vue";
import { getApiClient } from "../services/client";

const PAGE_SIZE = 50;

const items = ref<InspectionSummary[]>([]);
const loading = ref(false);
const loadingMore = ref(false);
const nextCursor = ref<string | null>(null);
const resultFilter = ref<"" | "OK" | "NG">("");
const barcodeFilter = ref("");
const productFilter = ref("");
const fromFilter = ref("");
const toFilter = ref("");

let searchTimer: number | undefined;
let requestSeq = 0;

function buildFilter(cursor?: string): InspectionFilter {
  return {
    ...(resultFilter.value ? { business_result: resultFilter.value } : {}),
    ...(barcodeFilter.value.trim() ? { barcode: barcodeFilter.value.trim() } : {}),
    ...(productFilter.value.trim() ? { product: productFilter.value.trim() } : {}),
    ...(fromFilter.value ? { from: fromFilter.value } : {}),
    ...(toFilter.value ? { to: toFilter.value } : {}),
    cursor,
    limit: PAGE_SIZE,
  };
}

function scheduleSearch(): void {
  window.clearTimeout(searchTimer);
  searchTimer = window.setTimeout(() => void load(), 300);
}

function resetAndLoad(): void {
  window.clearTimeout(searchTimer);
  void load();
}

async function load(): Promise<void> {
  const seq = ++requestSeq;
  nextCursor.value = null;
  loading.value = true;
  try {
    const page = await getApiClient().listInspections(buildFilter());
    if (seq !== requestSeq) return;
    items.value = page.items;
    nextCursor.value = page.next_cursor;
  } finally {
    if (seq === requestSeq) loading.value = false;
  }
}

async function loadMore(): Promise<void> {
  if (!nextCursor.value || loading.value || loadingMore.value) return;
  const seq = ++requestSeq;
  loadingMore.value = true;
  try {
    const page = await getApiClient().listInspections(buildFilter(nextCursor.value));
    if (seq !== requestSeq) return;
    items.value = [...items.value, ...page.items];
    nextCursor.value = page.next_cursor;
  } finally {
    if (seq === requestSeq) loadingMore.value = false;
  }
}

function onDateRange(range: unknown): void {
  const picked = (Array.isArray(range) ? range : []) as string[];
  fromFilter.value = picked[0] ?? "";
  toFilter.value = picked[1] ?? "";
  void load();
}

onMounted(load);
</script>

<template>
  <div class="inspections">
    <div class="inspections__filters">
      <el-select
        v-model="resultFilter"
        data-testid="inspection-result-filter"
        aria-label="Inspection result filter"
        placeholder="All results"
        clearable
        @change="resetAndLoad"
        style="width: 150px"
      >
        <el-option label="OK" value="OK" />
        <el-option label="NG" value="NG" />
      </el-select>
      <el-input
        v-model="barcodeFilter"
        placeholder="Barcode"
        clearable
        aria-label="Barcode filter"
        @input="scheduleSearch"
        style="width: 170px"
      />
      <el-input
        v-model="productFilter"
        placeholder="Product"
        clearable
        aria-label="Product filter"
        @input="scheduleSearch"
        style="width: 170px"
      />
      <el-date-picker
        type="datetimerange"
        start-placeholder="From"
        end-placeholder="To"
        value-format="YYYY-MM-DDTHH:mm:ssZ"
        @change="onDateRange"
        style="width: 320px"
      />
      <span class="inspections__count">{{ items.length }} rows</span>
    </div>

    <el-table :data="items" v-loading="loading" empty-text="No inspections found">
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
      <el-table-column prop="barcode" label="Barcode" width="140" />
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

    <div class="inspections__more">
      <el-button v-if="nextCursor" :loading="loadingMore" @click="loadMore">Load more</el-button>
    </div>
  </div>
</template>

<style scoped>
.inspections {
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.inspections__filters {
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
  align-items: center;
}
.inspections__count {
  color: var(--text-muted);
  font-size: 13px;
}
.inspections__more {
  display: flex;
  justify-content: center;
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

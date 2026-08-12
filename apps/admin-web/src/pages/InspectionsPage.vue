<script setup lang="ts">
import { onMounted, reactive, ref } from "vue";

import {
  apiClient,
  type Device,
  type InspectionPage,
  type InspectionQuery,
  type Line,
  type Site,
} from "@assemblyvision/api-client-central";

const query = reactive<InspectionQuery>({
  site_id: undefined,
  line_id: undefined,
  device_row_id: undefined,
  business_result: undefined,
  internal_decision: undefined,
  barcode: "",
  product: "",
  reason: "",
  rule_version: "",
  model_version: "",
  from_at: undefined,
  to_at: undefined,
  limit: 50,
});
const sites = ref<Site[]>([]);
const lines = ref<Line[]>([]);
const devices = ref<Device[]>([]);
const page = ref<InspectionPage | null>(null);
const error = ref<string | null>(null);
// Cursor used to reach each visited page; the first entry is the initial
// page (no cursor), so popping walks back one page at a time.
const cursorHistory = ref<(string | undefined)[]>([undefined]);

async function load(cursor?: string): Promise<void> {
  error.value = null;
  const params: InspectionQuery = { ...query, limit: query.limit };
  if (cursor) {
    params.cursor = cursor;
  }
  try {
    page.value = await apiClient.listInspections(params);
  } catch (err) {
    error.value = err instanceof Error ? err.message : "failed to load inspections";
  }
}

function apply(): void {
  cursorHistory.value = [undefined];
  load();
}

function next(): void {
  if (page.value?.next_cursor) {
    cursorHistory.value.push(page.value.next_cursor);
    load(page.value.next_cursor);
  }
}

function previous(): void {
  if (cursorHistory.value.length > 1) {
    cursorHistory.value.pop();
    load(cursorHistory.value[cursorHistory.value.length - 1]);
  }
}

onMounted(async () => {
  load();
  try {
    sites.value = await apiClient.listSites();
    devices.value = await apiClient.listDevices();
  } catch {
    // filters stay empty; history still loads
  }
});

async function onSiteChange(siteId?: number): Promise<void> {
  query.line_id = undefined;
  lines.value = siteId ? await apiClient.listLines(siteId) : [];
  apply();
}
</script>

<template>
  <main class="history">
    <header>
      <h1>Inspection history</h1>
      <p class="muted">Cross-device records with bounded filters and keyset pagination.</p>
    </header>

    <el-card class="block">
      <div class="filters">
        <el-select
          v-model="query.business_result"
          placeholder="Result"
          clearable
          class="filter"
          @change="apply"
        >
          <el-option label="OK" value="OK" />
          <el-option label="NG" value="NG" />
        </el-select>
        <el-select
          v-model="query.internal_decision"
          placeholder="Internal decision"
          clearable
          class="filter"
          @change="apply"
        >
          <el-option label="OK" value="OK" />
          <el-option label="NG" value="NG" />
          <el-option label="Uncertain" value="UNCERTAIN" />
        </el-select>
        <el-select v-model="query.site_id" placeholder="Site" clearable class="filter" @change="onSiteChange">
          <el-option v-for="site in sites" :key="site.id" :label="site.name" :value="site.id" />
        </el-select>
        <el-select v-model="query.line_id" placeholder="Line" clearable class="filter" @change="apply">
          <el-option v-for="line in lines" :key="line.id" :label="line.name" :value="line.id" />
        </el-select>
        <el-select
          v-model="query.device_row_id"
          placeholder="Device"
          clearable
          class="filter"
          @change="apply"
        >
          <el-option
            v-for="device in devices"
            :key="device.id"
            :label="device.device_id"
            :value="device.id"
          />
        </el-select>
        <el-date-picker
          v-model="query.from_at"
          type="date"
          placeholder="From (UTC)"
          value-format="YYYY-MM-DDT00:00:00.000Z"
          class="filter"
          @change="apply"
        />
        <el-date-picker
          v-model="query.to_at"
          type="date"
          placeholder="To (UTC)"
          value-format="YYYY-MM-DDT00:00:00.000Z"
          class="filter"
          @change="apply"
        />
        <el-input v-model="query.barcode" placeholder="Barcode" clearable class="filter" @change="apply" />
        <el-input v-model="query.product" placeholder="Product" clearable class="filter" @change="apply" />
        <el-input v-model="query.reason" placeholder="Reason code" clearable class="filter" @change="apply" />
        <el-input v-model="query.rule_version" placeholder="Rule version id" clearable class="filter" @change="apply" />
        <el-input v-model="query.model_version" placeholder="Model version id" clearable class="filter" @change="apply" />
      </div>
      <div class="filter-actions">
        <el-button type="primary" @click="apply">Apply</el-button>
        <el-button
          @click="
            query.site_id = undefined;
            query.line_id = undefined;
            query.device_row_id = undefined;
            query.business_result = undefined;
            query.internal_decision = undefined;
            query.barcode = '';
            query.product = '';
            query.reason = '';
            query.rule_version = '';
            query.model_version = '';
            query.from_at = undefined;
            query.to_at = undefined;
            apply();
          "
        >
          Clear
        </el-button>
      </div>
    </el-card>

    <el-alert v-if="error" :title="error" type="error" show-icon class="block" />

    <el-card class="block">
      <el-table v-if="page" :data="page.items" empty-text="No inspections match the filters.">
        <el-table-column prop="completed_at" label="Completed (UTC)" width="180">
          <template #default="{ row }">{{ new Date(row.completed_at).toLocaleString() }}</template>
        </el-table-column>
        <el-table-column prop="device_id" label="Device" width="220" />
        <el-table-column prop="barcode_value" label="Barcode" width="140" />
        <el-table-column prop="product_code" label="Product" width="120" />
        <el-table-column label="Result" width="100">
          <template #default="{ row }">
            <el-tag :type="row.business_result === 'OK' ? 'success' : 'danger'">
              {{ row.business_result }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="Internal" width="110">
          <template #default="{ row }">{{ row.internal_decision }}</template>
        </el-table-column>
        <el-table-column label="Upload delay" width="120">
          <template #default="{ row }">{{ row.upload_delay_ms }} ms</template>
        </el-table-column>
        <el-table-column label="" width="90">
          <template #default="{ row }">
            <router-link :to="`/inspections/${row.inspection_id}`">Detail</router-link>
          </template>
        </el-table-column>
      </el-table>
      <div class="pager">
        <el-button :disabled="cursorHistory.length === 0" @click="previous">Previous</el-button>
        <el-button
          v-if="page?.next_cursor"
          type="primary"
          plain
          @click="next"
        >
          Next page
        </el-button>
      </div>
    </el-card>
  </main>
</template>

<style scoped>
.history {
  max-width: 1200px;
  margin: 0 auto;
  padding: 1.5rem;
}

.block {
  margin-top: 1rem;
}

.filters {
  display: flex;
  gap: 0.75rem;
  flex-wrap: wrap;
}

.filter {
  width: 190px;
}

.filter-actions {
  margin-top: 0.75rem;
  display: flex;
  gap: 0.5rem;
}

.pager {
  margin-top: 1rem;
  display: flex;
  gap: 0.5rem;
  justify-content: flex-end;
}

.muted {
  color: #909399;
}
</style>

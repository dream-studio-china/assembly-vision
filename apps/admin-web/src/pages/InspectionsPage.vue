<script setup lang="ts">
import { onMounted, reactive, ref } from "vue";
import { useI18n } from "vue-i18n";

import {
  apiClient,
  type Device,
  type InspectionPage,
  type InspectionQuery,
  type Line,
  type Site,
} from "@assemblyvision/api-client-central";

import { formatMillis } from "../lib/format";

const { t, locale } = useI18n();
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
const loading = ref(false);
// Cursor used to reach each visited page; the first entry is the initial
// page (no cursor), so popping walks back one page at a time.
const cursorHistory = ref<(string | undefined)[]>([undefined]);
// Monotonic request generation: a stale in-flight response (e.g. a slow
// "next" that resolves after a filter reset) is discarded, so the table
// never shows data that disagrees with the cursor history.
let requestGeneration = 0;

async function load(cursor?: string): Promise<void> {
  error.value = null;
  const generation = ++requestGeneration;
  const params: InspectionQuery = { ...query, limit: query.limit };
  if (cursor) {
    params.cursor = cursor;
  }
  loading.value = true;
  try {
    const result = await apiClient.listInspections(params);
    if (generation !== requestGeneration) {
      return; // superseded by a newer load
    }
    page.value = result;
  } catch (err) {
    if (generation !== requestGeneration) {
      return;
    }
    error.value = err instanceof Error ? err.message : t("failed to load inspections");
  } finally {
    if (generation === requestGeneration) {
      loading.value = false;
    }
  }
}

function apply(): void {
  cursorHistory.value = [undefined];
  void load();
}

function next(): void {
  if (loading.value || !page.value?.next_cursor) {
    return;
  }
  cursorHistory.value.push(page.value.next_cursor);
  void load(page.value.next_cursor);
}

function previous(): void {
  if (loading.value || cursorHistory.value.length <= 1) {
    return;
  }
  cursorHistory.value.pop();
  void load(cursorHistory.value[cursorHistory.value.length - 1]);
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
      <h1>{{ t("Inspection history") }}</h1>
      <p class="muted">
        {{ t("Cross-device records with bounded filters and keyset pagination.") }}
      </p>
    </header>

    <el-card class="block">
      <div class="filters">
        <el-select
          v-model="query.business_result"
          :placeholder="t('Result')"
          clearable
          class="filter"
          @change="apply"
        >
          <el-option :label="t('OK')" value="OK" />
          <el-option :label="t('NG')" value="NG" />
        </el-select>
        <el-select
          v-model="query.internal_decision"
          :placeholder="t('Internal decision')"
          clearable
          class="filter"
          @change="apply"
        >
          <el-option :label="t('OK')" value="OK" />
          <el-option :label="t('NG')" value="NG" />
          <el-option :label="t('Uncertain')" value="UNCERTAIN" />
        </el-select>
        <el-select v-model="query.site_id" :placeholder="t('Site')" clearable class="filter" @change="onSiteChange">
          <el-option v-for="site in sites" :key="site.id" :label="site.name" :value="site.id" />
        </el-select>
        <el-select v-model="query.line_id" :placeholder="t('Line')" clearable class="filter" @change="apply">
          <el-option v-for="line in lines" :key="line.id" :label="line.name" :value="line.id" />
        </el-select>
        <el-select
          v-model="query.device_row_id"
          :placeholder="t('Device')"
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
          :placeholder="t('From (UTC)')"
          value-format="YYYY-MM-DDT00:00:00.000Z"
          class="filter"
          @change="apply"
        />
        <el-date-picker
          v-model="query.to_at"
          type="date"
          :placeholder="t('To (UTC)')"
          value-format="YYYY-MM-DDT00:00:00.000Z"
          class="filter"
          @change="apply"
        />
        <el-input v-model="query.barcode" :placeholder="t('Barcode')" clearable class="filter" @change="apply" />
        <el-input v-model="query.product" :placeholder="t('Product')" clearable class="filter" @change="apply" />
        <el-input v-model="query.reason" :placeholder="t('Reason code')" clearable class="filter" @change="apply" />
        <el-input v-model="query.rule_version" :placeholder="t('Rule version id')" clearable class="filter" @change="apply" />
        <el-input v-model="query.model_version" :placeholder="t('Model version id')" clearable class="filter" @change="apply" />
      </div>
      <div class="filter-actions">
        <el-button type="primary" @click="apply">{{ t("Apply") }}</el-button>
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
          {{ t("Clear") }}
        </el-button>
      </div>
    </el-card>

    <el-alert v-if="error" :title="error" type="error" show-icon class="block" />

    <el-card class="block">
      <el-table v-if="page" :data="page.items" :empty-text="t('No inspections match the filters.')">
        <el-table-column prop="completed_at" :label="t('Completed (UTC)')" width="200" show-overflow-tooltip>
          <template #default="{ row }">{{ new Date(row.completed_at).toLocaleString() }}</template>
        </el-table-column>
        <el-table-column prop="device_id" :label="t('Device')" width="260" show-overflow-tooltip />
        <el-table-column prop="barcode_value" :label="t('Barcode')" width="150" show-overflow-tooltip />
        <el-table-column prop="product_code" :label="t('Product')" width="120" />
        <el-table-column :label="t('Result')" width="100">
          <template #default="{ row }">
            <el-tag :type="row.business_result === 'OK' ? 'success' : 'danger'">
              {{ row.business_result }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column :label="t('Internal')" width="110">
          <template #default="{ row }">{{ row.internal_decision }}</template>
        </el-table-column>
        <el-table-column :label="t('Upload delay')" width="140">
          <template #default="{ row }">{{ formatMillis(row.upload_delay_ms, locale) }}</template>
        </el-table-column>
        <el-table-column label="" width="90">
          <template #default="{ row }">
            <router-link :to="`/inspections/${row.inspection_id}`">{{ t("Detail") }}</router-link>
          </template>
        </el-table-column>
      </el-table>
      <div class="pager">
        <el-button :disabled="cursorHistory.length <= 1" @click="previous">{{ t("Previous") }}</el-button>
        <el-button
          v-if="page?.next_cursor"
          type="primary"
          plain
          :loading="loading"
          @click="next"
        >
          {{ t("Next page") }}
        </el-button>
      </div>
    </el-card>
  </main>
</template>

<style scoped>
.history {
  max-width: 1200px;
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
  width: 170px;
}

.filter-actions {
  margin-top: 0.75rem;
  display: flex;
  gap: 0.5rem;
}

.pager {
  margin-top: 0.75rem;
  display: flex;
  gap: 0.5rem;
  justify-content: flex-end;
}

.muted {
  color: var(--text-muted);
}
</style>

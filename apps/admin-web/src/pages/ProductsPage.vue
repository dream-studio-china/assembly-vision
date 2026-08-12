<script setup lang="ts">
import { onMounted, ref } from "vue";
import { useI18n } from "vue-i18n";

import { apiClient, type ProductPage } from "@assemblyvision/api-client-central";

const { t } = useI18n();
const page = ref<ProductPage | null>(null);
const error = ref<string | null>(null);

onMounted(async () => {
  try {
    page.value = await apiClient.listProducts();
  } catch (err) {
    error.value = err instanceof Error ? err.message : t("Failed to load products.");
  }
});
</script>

<template>
  <main class="products">
    <header>
      <h1>{{ t("Products") }}</h1>
      <p class="muted">
        {{ t("Stable product identities with immutable governed versions.") }}
      </p>
    </header>

    <el-alert
      type="warning"
      show-icon
      :closable="false"
      class="notice"
      :title="t('Desired configuration only. Packages are installed manually in M1. Assignment is not proof of download, validation, or activation.')"
    />

    <el-alert v-if="error" :title="error" type="error" show-icon class="block" />

    <el-card class="block">
      <el-table v-if="page" :data="page.items" :empty-text="t('No products yet.')">
        <el-table-column prop="product_code" :label="t('Product code')" width="180" show-overflow-tooltip />
        <el-table-column prop="name" :label="t('Product')" min-width="180" show-overflow-tooltip />
        <el-table-column prop="version_count" :label="t('Versions')" width="100" />
        <el-table-column :label="t('Latest version')" width="140">
          <template #default="{ row }">
            <template v-if="row.latest_version_id">
              <el-tag :type="row.latest_version_status === 'PUBLISHED' ? 'success' : 'info'" size="small">
                v{{ row.latest_version_number }}
              </el-tag>
              <span class="muted small">{{ row.latest_version_status }}</span>
            </template>
            <span v-else class="muted">{{ t("Draft") }}</span>
          </template>
        </el-table-column>
        <el-table-column :label="t('Created (UTC)')" width="200" show-overflow-tooltip>
          <template #default="{ row }">{{ new Date(row.created_at).toLocaleString() }}</template>
        </el-table-column>
        <el-table-column label="" width="90">
          <template #default="{ row }">
            <router-link :to="`/products/${row.id}`">{{ t("Detail") }}</router-link>
          </template>
        </el-table-column>
      </el-table>
    </el-card>
  </main>
</template>

<style scoped>
.products {
  max-width: 1100px;
  margin: 0 auto;
  padding: 1rem;
}

.notice {
  margin-top: 0.75rem;
}

.block {
  margin-top: 0.75rem;
}

.muted {
  color: var(--text-muted);
}

.small {
  font-size: 12px;
  margin-left: 0.35rem;
}
</style>

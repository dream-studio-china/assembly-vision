<script setup lang="ts">
import { onMounted, ref } from "vue";
import { useI18n } from "vue-i18n";
import { useRoute } from "vue-router";

import { apiClient, type ProductDetail } from "@assemblyvision/api-client-central";

const { t } = useI18n();
const route = useRoute();
const detail = ref<ProductDetail | null>(null);
const error = ref<string | null>(null);

onMounted(async () => {
  try {
    detail.value = await apiClient.getProduct(Number(route.params.id));
  } catch (err) {
    error.value = err instanceof Error ? err.message : t("Failed to load the product.");
  }
});
</script>

<template>
  <main class="detail">
    <header>
      <h1>{{ t("Product {code}", { code: detail?.product_code ?? route.params.id }) }}</h1>
      <router-link to="/products" class="back">{{ t("Back to products") }}</router-link>
    </header>

    <el-alert
      type="warning"
      show-icon
      :closable="false"
      class="notice"
      :title="t('Desired configuration only. Packages are installed manually in M1. Assignment is not proof of download, validation, or activation.')"
    />

    <el-alert v-if="error" :title="error" type="error" show-icon class="block" />

    <template v-if="detail">
      <el-card class="block">
        <template #header>{{ t("Product") }}</template>
        <el-descriptions :column="3" border>
          <el-descriptions-item :label="t('Product code')">{{ detail.product_code }}</el-descriptions-item>
          <el-descriptions-item :label="t('Product')">{{ detail.name }}</el-descriptions-item>
          <el-descriptions-item :label="t('Created (UTC)')">
            {{ new Date(detail.created_at).toLocaleString() }}
          </el-descriptions-item>
        </el-descriptions>
      </el-card>

      <h2 class="section">{{ t("Governed versions") }}</h2>
      <el-empty v-if="detail.versions.length === 0" :description="t('No versions yet.')" />
      <el-card v-for="version in detail.versions" :key="version.version_id" class="block">
        <template #header>
          <span>{{ t("Version {n}", { n: version.version }) }}</span>
          <el-tag :type="version.status === 'PUBLISHED' ? 'success' : 'info'" size="small">
            {{ version.status === "PUBLISHED" ? t("Published") : t("Draft") }}
          </el-tag>
        </template>

        <el-descriptions :column="2" border>
          <el-descriptions-item :label="t('Version')">{{ version.version_id }}</el-descriptions-item>
          <el-descriptions-item :label="t('Status')">{{ version.status }}</el-descriptions-item>
          <el-descriptions-item :label="t('Published at')">
            {{ version.published_at ? new Date(version.published_at).toLocaleString() : "—" }}
          </el-descriptions-item>
          <el-descriptions-item :label="t('Published by')">{{ version.published_by ?? "—" }}</el-descriptions-item>
          <el-descriptions-item :label="t('Publish reason')" :span="2">
            {{ version.publish_reason ?? "—" }}
          </el-descriptions-item>
        </el-descriptions>

        <h3 class="sub">{{ t("Barcode mappings") }}</h3>
        <el-empty
          v-if="version.barcodes.length === 0"
          :description="t('No barcode mappings.')"
          :image-size="40"
        />
        <ul v-else class="chips">
          <li v-for="barcode in version.barcodes" :key="barcode" class="chip">{{ barcode }}</li>
        </ul>

        <h3 class="sub">{{ t("Required components") }}</h3>
        <el-empty
          v-if="version.components.length === 0"
          :description="t('No components defined.')"
          :image-size="40"
        />
        <el-table v-else :data="version.components" size="small">
          <el-table-column prop="component_code" :label="t('Component')" />
          <el-table-column prop="expected_count" :label="t('Expected count')" width="140" />
        </el-table>
      </el-card>
    </template>
  </main>
</template>

<style scoped>
.detail {
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

.section {
  margin-top: 1.25rem;
}

.sub {
  margin: 1rem 0 0.5rem;
}

.back {
  color: var(--text-muted);
}

.chips {
  list-style: none;
  display: flex;
  flex-wrap: wrap;
  gap: 0.4rem;
  padding: 0;
  margin: 0;
}

.chip {
  padding: 0.2rem 0.6rem;
  border: 1px solid var(--border);
  background: var(--shell-strong);
  font-family: var(--font-mono);
  font-size: 12px;
}
</style>

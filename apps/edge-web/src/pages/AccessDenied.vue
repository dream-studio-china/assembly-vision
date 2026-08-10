<script setup lang="ts">
import { useI18n } from "vue-i18n";
import { useRouter } from "vue-router";

const { t } = useI18n();
const router = useRouter();
</script>

<template>
  <section class="access-denied">
    <h2>{{ t("Access denied") }}</h2>
    <p>
      {{ t("Your viewer session does not have administrator permission for the requested area. The configuration, logs, and developer tool screens are restricted to edge administrators.") }}
    </p>
    <el-button type="primary" @click="router.push('/')">{{ t("Back to overview") }}</el-button>
  </section>
</template>

<style scoped>
.access-denied {
  max-width: 480px;
  display: grid;
  gap: 16px;
  justify-items: start;
}
</style>

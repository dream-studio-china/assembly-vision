<script setup lang="ts">
import { useRouter } from "vue-router";

const router = useRouter();
</script>

<template>
  <section class="access-denied">
    <h2>Access denied</h2>
    <p>
      Your viewer session does not have administrator permission for the requested area. The
      configuration, logs, and developer tool screens are restricted to edge administrators.
    </p>
    <el-button type="primary" @click="router.push('/')">Back to overview</el-button>
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

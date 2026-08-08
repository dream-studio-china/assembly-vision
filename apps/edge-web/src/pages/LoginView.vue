<script setup lang="ts">
import { ref } from "vue";
import { useRoute, useRouter } from "vue-router";
import { createViewerSession, isHttpMode } from "../services/client";

const route = useRoute();
const router = useRouter();
const token = ref("");
const error = ref<string | null>(null);
const submitting = ref(false);

async function signIn(): Promise<void> {
  error.value = null;
  submitting.value = true;
  try {
    await createViewerSession(token.value);
    token.value = "";
    const next = route.query.next;
    await router.replace(typeof next === "string" && next.startsWith("/") ? next : "/");
  } catch (reason) {
    error.value = reason instanceof Error ? reason.message : "Sign-in failed.";
  } finally {
    submitting.value = false;
  }
}
</script>

<template>
  <section class="login">
    <h2>Edge viewer sign in</h2>
    <p v-if="isHttpMode()">
      Enter the viewer token configured for this edge service. It is exchanged for an HttpOnly
      same-origin session and is not stored by the dashboard.
    </p>
    <p v-else>Sign-in is only required when the dashboard uses the HTTP edge API.</p>
    <el-alert v-if="error" :title="error" type="error" show-icon :closable="false" />
    <el-form v-if="isHttpMode()" @submit.prevent="signIn">
      <el-form-item label="Viewer token">
        <el-input v-model="token" type="password" show-password autocomplete="current-password" />
      </el-form-item>
      <el-button type="primary" native-type="submit" :loading="submitting" :disabled="!token">
        Sign in
      </el-button>
    </el-form>
  </section>
</template>

<style scoped>
.login {
  max-width: 480px;
  display: grid;
  gap: 16px;
}
</style>

<script setup lang="ts">
import { computed, ref } from "vue";
import { useI18n } from "vue-i18n";
import { useRoute, useRouter } from "vue-router";
import { createViewerSession, isHttpMode } from "../services/client";
import { useSessionStore } from "../stores/session";

const { t } = useI18n();
const route = useRoute();
const router = useRouter();
const session = useSessionStore();
const token = ref("");
const error = ref<string | null>(null);
const submitting = ref(false);

const nextPath = computed(() =>
  typeof route.query.next === "string" && route.query.next.startsWith("/") ? route.query.next : "/",
);

async function signIn(): Promise<void> {
  error.value = null;
  submitting.value = true;
  try {
    await createViewerSession(token.value);
    token.value = "";
    await session.check();
    await router.replace(nextPath.value);
  } catch (reason) {
    error.value = reason instanceof Error ? reason.message : t("Sign-in failed.");
  } finally {
    submitting.value = false;
  }
}
</script>

<template>
  <section class="login">
    <h2>{{ t("Edge viewer sign in") }}</h2>
    <p v-if="isHttpMode()">
      {{ t("Enter the viewer token configured for this edge service. It is exchanged for an HttpOnly same-origin session and is not stored by the dashboard.") }}
    </p>
    <p v-else>{{ t("Sign-in is only required when the dashboard uses the HTTP edge API.") }}</p>
    <p v-if="isHttpMode() && nextPath !== '/'" class="login__destination">
      {{ t("After signing in you will return to {path}.", { path: nextPath }) }}
    </p>
    <el-alert v-if="error" :title="error" type="error" show-icon :closable="false" />
    <el-form v-if="isHttpMode()" @submit.prevent="signIn">
      <el-form-item :label="t('Viewer token')">
        <el-input v-model="token" type="password" show-password autocomplete="current-password" />
      </el-form-item>
      <el-button type="primary" native-type="submit" :loading="submitting" :disabled="!token">
        {{ t("Sign in") }}
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
.login__destination {
  color: var(--shell-muted);
}
</style>

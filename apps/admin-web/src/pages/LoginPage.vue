<script setup lang="ts">
import { ref } from "vue";
import { useRouter } from "vue-router";

import { ElMessage } from "element-plus";

import { useSessionStore } from "../stores/session";

const session = useSessionStore();
const router = useRouter();
const token = ref("");
const submitting = ref(false);

async function submit(): Promise<void> {
  if (!token.value.trim()) {
    return;
  }
  submitting.value = true;
  try {
    await session.login(token.value.trim());
    await router.push("/");
  } catch {
    ElMessage.error("Authentication failed; check the pilot administrator token.");
  } finally {
    submitting.value = false;
  }
}
</script>

<template>
  <main class="login">
    <el-card class="login-card">
      <h1>AssemblyVision Central</h1>
      <p class="muted">Pilot administrator sign-in</p>
      <el-form @submit.prevent="submit">
        <el-form-item>
          <el-input
            v-model="token"
            type="password"
            placeholder="Administrator token"
            show-password
            @keyup.enter="submit"
          />
        </el-form-item>
        <el-button type="primary" :loading="submitting" class="full" @click="submit">
          Sign in
        </el-button>
      </el-form>
    </el-card>
  </main>
</template>

<style scoped>
.login {
  min-height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
}

.login-card {
  width: 360px;
}

.full {
  width: 100%;
}

.muted {
  color: #909399;
}
</style>

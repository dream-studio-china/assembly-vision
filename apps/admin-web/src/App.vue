<script setup lang="ts">
import { onMounted } from "vue";
import { useRouter } from "vue-router";

import { useSessionStore } from "./stores/session";

const session = useSessionStore();
const router = useRouter();

onMounted(async () => {
  const restored = await session.restore();
  if (!restored && router.currentRoute.value.name !== "login") {
    await router.push("/login");
  }
});

async function signOut(): Promise<void> {
  session.clear();
  await router.push("/login");
}
</script>

<template>
  <div class="app">
    <header v-if="session.isAuthenticated" class="topbar">
      <span class="brand">AssemblyVision Central</span>
      <nav class="nav">
        <router-link to="/">Overview</router-link>
        <router-link to="/inspections">Inspections</router-link>
      </nav>
      <span class="user">
        {{ session.me?.username ?? "pilot-admin" }}
        <el-button link type="danger" @click="signOut">Sign out</el-button>
      </span>
    </header>
    <RouterView />
  </div>
</template>

<style scoped>
.topbar {
  display: flex;
  align-items: center;
  gap: 1.5rem;
  padding: 0.75rem 1.5rem;
  border-bottom: 1px solid #e4e7ed;
  background: #fff;
}

.brand {
  font-weight: 600;
}

.nav {
  display: flex;
  gap: 1rem;
  flex: 1;
}

.nav a {
  color: #606266;
  text-decoration: none;
}

.nav a.router-link-active {
  color: #409eff;
  font-weight: 600;
}

.user {
  color: #909399;
  display: flex;
  align-items: center;
  gap: 0.5rem;
}
</style>

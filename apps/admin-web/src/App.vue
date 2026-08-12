<script setup lang="ts">
import { computed, onMounted } from "vue";
import { useI18n } from "vue-i18n";
import { useRouter } from "vue-router";
import enLocale from "element-plus/es/locale/lang/en";
import zhCnLocale from "element-plus/es/locale/lang/zh-cn";
import zhTwLocale from "element-plus/es/locale/lang/zh-tw";
import jaLocale from "element-plus/es/locale/lang/ja";

import { useSessionStore } from "./stores/session";
import { activeLocale, applyLocale, isSupportedLocale, SUPPORTED_LOCALES } from "./i18n";

const { t } = useI18n();
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

// Element Plus built-in texts (date pickers, dialogs, ...) follow the same
// locale as the dashboard strings.
const elementLocale = computed(() => {
  switch (activeLocale.value) {
    case "zh-CN":
      return zhCnLocale;
    case "zh-HK":
      return zhTwLocale;
    case "ja":
      return jaLocale;
    default:
      return enLocale;
  }
});

function selectLocale(command: string | number | object): void {
  const value = typeof command === "string" ? command : "";
  if (!isSupportedLocale(value)) return;
  try {
    applyLocale(value, window.localStorage);
  } catch {
    applyLocale(value);
  }
}
</script>

<template>
  <el-config-provider :locale="elementLocale">
    <div class="app">
      <header v-if="session.isAuthenticated" class="topbar">
        <span class="brand">AssemblyVision Central</span>
        <nav class="nav" :aria-label="t('Primary navigation')">
          <router-link to="/">{{ t("Overview") }}</router-link>
          <router-link to="/inspections">{{ t("Inspections") }}</router-link>
          <router-link to="/reviews">{{ t("Reviews") }}</router-link>
        </nav>
        <el-dropdown
          class="locale"
          trigger="click"
          :teleported="false"
          data-testid="locale-selector"
          @command="selectLocale"
        >
          <button
            type="button"
            class="locale-trigger"
            :aria-label="t('Interface language')"
            :title="t('Interface language')"
          >
            <svg
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              stroke-width="2"
              stroke-linecap="round"
              stroke-linejoin="round"
              aria-hidden="true"
            >
              <circle cx="12" cy="12" r="10" />
              <path d="M2 12h20" />
              <path d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z" />
            </svg>
          </button>
          <template #dropdown>
            <el-dropdown-menu class="locale-menu">
              <el-dropdown-item
                v-for="locale in SUPPORTED_LOCALES"
                :key="locale.value"
                :command="locale.value"
                :class="{ 'is-active': locale.value === activeLocale }"
              >
                <svg
                  v-if="locale.value === activeLocale"
                  class="locale-check"
                  viewBox="0 0 24 24"
                  fill="none"
                  stroke="currentColor"
                  stroke-width="2.5"
                  stroke-linecap="round"
                  stroke-linejoin="round"
                  aria-hidden="true"
                >
                  <path d="M20 6 9 17l-5-5" />
                </svg>
                <span v-else class="locale-check" aria-hidden="true" />
                {{ locale.label }}
              </el-dropdown-item>
            </el-dropdown-menu>
          </template>
        </el-dropdown>
        <span class="user">
          {{ session.me?.username ?? "pilot-admin" }}
          <el-button link type="danger" @click="signOut">{{ t("Sign out") }}</el-button>
        </span>
      </header>
      <RouterView />
    </div>
  </el-config-provider>
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

.locale-trigger {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 30px;
  height: 30px;
  padding: 0;
  border: 1px solid #dcdfe6;
  border-radius: 4px;
  background: #fff;
  color: #606266;
  cursor: pointer;
}

.locale-trigger:hover,
.locale-trigger:focus-visible {
  color: #409eff;
  border-color: #409eff;
}

.locale-trigger svg {
  width: 16px;
  height: 16px;
}

.locale-menu :deep(.el-dropdown-menu__item) {
  font-size: 13px;
  display: flex;
  align-items: center;
  gap: 6px;
}

.locale-check {
  flex: 0 0 14px;
  width: 14px;
  height: 14px;
}
</style>

<script setup lang="ts">
import { formatBytes } from "@assemblyvision/ui";
import { computed, onBeforeUnmount, onMounted, ref } from "vue";
import { useI18n } from "vue-i18n";
import enLocale from "element-plus/es/locale/lang/en";
import zhCnLocale from "element-plus/es/locale/lang/zh-cn";
import zhTwLocale from "element-plus/es/locale/lang/zh-tw";
import jaLocale from "element-plus/es/locale/lang/ja";
import { useRuntimeStore } from "./stores/runtime";
import { useSessionStore } from "./stores/session";
import { isHttpMode } from "./services/client";
import { activeLocale, applyLocale, isSupportedLocale, SUPPORTED_LOCALES } from "./i18n";
import { activeTheme, applyTheme, themes } from "./theme";

const { t } = useI18n();
const runtime = useRuntimeStore();
const session = useSessionStore();
const localTime = ref(new Date());
let clockTimer: ReturnType<typeof setInterval> | null = null;

const deviceCode = computed(() => runtime.status?.device_id.slice(0, 8).toUpperCase() ?? "LOCAL EDGE");
const diskWarning = computed(() => runtime.status?.storage_mode !== undefined && runtime.status.storage_mode !== "NORMAL");
// Admin-only links are always shown in mock mode; in HTTP mode they appear
// only for an authenticated administrator (design 16.3).
const showAdminLinks = computed(() => !isHttpMode() || (session.authenticated && session.admin));

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

function selectTheme(): void {
  try {
    applyTheme(activeTheme.value, window.localStorage);
  } catch {
    applyTheme(activeTheme.value);
  }
}

function selectLocale(command: string | number | object): void {
  const value = typeof command === "string" ? command : "";
  if (!isSupportedLocale(value)) return;
  try {
    applyLocale(value, window.localStorage);
  } catch {
    applyLocale(value);
  }
}

onMounted(() => {
  void runtime.refresh();
  clockTimer = setInterval(() => {
    localTime.value = new Date();
  }, 1000);
});

onBeforeUnmount(() => {
  if (clockTimer !== null) clearInterval(clockTimer);
});
</script>

<template>
  <el-config-provider :locale="elementLocale">
    <el-container class="app-shell">
      <el-header class="app-shell__header">
        <div class="app-shell__brand">
          <span>AssemblyVision</span>
          <small>{{ t("EDGE / {code}", { code: deviceCode }) }}</small>
        </div>
        <nav class="app-shell__nav" :aria-label="t('Primary navigation')">
          <router-link to="/">{{ t("Operator") }}</router-link>
          <router-link to="/live">{{ t("Live") }}</router-link>
          <router-link to="/history">{{ t("History") }}</router-link>
          <router-link to="/review">{{ t("Review") }}</router-link>
          <router-link to="/statistics">{{ t("Statistics") }}</router-link>
          <router-link to="/uploads">{{ t("Uploads") }}</router-link>
          <router-link to="/health">{{ t("Health") }}</router-link>
          <router-link v-if="showAdminLinks" to="/configuration">{{ t("Config") }}</router-link>
          <router-link v-if="showAdminLinks" to="/logs">{{ t("Logs") }}</router-link>
          <router-link v-if="showAdminLinks" to="/dev">{{ t("Dev") }}</router-link>
          <router-link v-if="isHttpMode() && !session.authenticated" to="/login">{{ t("Sign in") }}</router-link>
          <span v-else-if="isHttpMode() && session.authenticated" class="app-shell__session-chip">
            {{ t("Viewer session") }}
          </span>
        </nav>
        <div class="app-shell__telemetry" :aria-label="t('Device telemetry')">
          <span
            class="dot"
            :class="runtime.status?.inspection_ready ? 'dot--ok' : 'dot--ng'"
            aria-hidden="true"
          />
          <span>{{ runtime.status?.operational_state ?? t("Loading") }}</span>
          <span class="app-shell__telemetry-item">
            {{
              t("Central: {state}", {
                state: runtime.status?.central_connected ? t("connected") : t("offline"),
              })
            }}
          </span>
          <span v-if="runtime.status" :class="{ 'app-shell__disk-warning': diskWarning }" class="app-shell__telemetry-item">
            {{ t("Disk: {bytes} free", { bytes: formatBytes(runtime.status.disk_free_bytes) }) }}
          </span>
          <time class="app-shell__clock" :datetime="localTime.toISOString()">
            {{ localTime.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" }) }}
          </time>
          <el-dropdown
            class="app-shell__locale"
            trigger="click"
            :teleported="false"
            data-testid="locale-selector"
            @command="selectLocale"
          >
            <button
              type="button"
              class="app-shell__locale-trigger"
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
              <el-dropdown-menu class="app-shell__locale-menu">
                <el-dropdown-item
                  v-for="locale in SUPPORTED_LOCALES"
                  :key="locale.value"
                  :command="locale.value"
                  :class="{ 'is-active': locale.value === activeLocale }"
                >
                  <svg
                    v-if="locale.value === activeLocale"
                    class="app-shell__locale-check"
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
                  <span v-else class="app-shell__locale-check" aria-hidden="true" />
                  {{ locale.label }}
                </el-dropdown-item>
              </el-dropdown-menu>
            </template>
          </el-dropdown>
          <el-select
            v-model="activeTheme"
            class="app-shell__theme-select"
            data-testid="theme-selector"
            :teleported="false"
            :aria-label="t('Interface theme')"
            @change="selectTheme"
          >
            <el-option v-for="theme in themes" :key="theme.value" :label="theme.label" :value="theme.value" />
          </el-select>
        </div>
      </el-header>
      <el-main class="app-shell__main">
        <router-view />
      </el-main>
    </el-container>
  </el-config-provider>
</template>

<style>
html,
body,
#app {
  margin: 0;
  height: 100%;
}
</style>

<style scoped>
.app-shell {
  height: 100%;
}
.app-shell__header {
  display: flex;
  align-items: center;
  gap: 16px;
  min-height: 58px;
  height: auto;
  padding: 8px 18px;
  background: var(--shell);
  color: var(--shell-text);
  border-bottom: 3px solid var(--accent);
}
.app-shell__brand {
  display: flex;
  flex-direction: column;
  color: var(--shell-text);
  font-weight: 750;
  letter-spacing: 0.02em;
  white-space: nowrap;
}
.app-shell__brand small {
  margin-top: 2px;
  color: var(--shell-muted);
  font-size: 10px;
  font-weight: 700;
  letter-spacing: 0.08em;
}
.app-shell__nav {
  display: flex;
  align-items: center;
  gap: 4px;
  flex: 1;
  min-width: 0;
  overflow-x: auto;
}
.app-shell__nav a {
  color: var(--shell-muted);
  text-decoration: none;
  font-size: 14px;
  white-space: nowrap;
  padding: 7px 9px;
  border-radius: var(--radius-small);
}
.app-shell__nav a.router-link-active {
  color: var(--shell-text);
  background: var(--accent);
  font-weight: 600;
}
.app-shell__telemetry {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 13px;
  white-space: nowrap;
}
.app-shell__telemetry-item { color: var(--shell-muted); }
.app-shell__clock {
  color: var(--shell-text);
  font-variant-numeric: tabular-nums;
  font-weight: 600;
}
.app-shell__disk-warning { color: var(--status-warning); }
.app-shell__session-chip {
  color: var(--status-ok);
  font-size: 12px;
  font-weight: 600;
  white-space: nowrap;
  padding: 3px 10px;
  border: 1px solid var(--status-ok);
  border-radius: 999px;
}
.dot {
  width: 10px;
  height: 10px;
  border-radius: 50%;
  display: inline-block;
}
.dot--ok {
  background: var(--status-ok);
}
.dot--ng {
  background: var(--status-ng);
}
.app-shell__theme-select { width: 150px; }
.app-shell__locale-trigger {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 30px;
  height: 30px;
  padding: 0;
  border: 1px solid var(--border-strong);
  border-radius: var(--radius-small);
  background: var(--shell-strong);
  color: var(--shell-muted);
  cursor: pointer;
}
.app-shell__locale-trigger:hover,
.app-shell__locale-trigger:focus-visible {
  color: var(--shell-text);
  border-color: var(--accent);
}
.app-shell__locale-trigger svg {
  width: 16px;
  height: 16px;
}
.app-shell__locale :deep(.el-dropdown-menu) {
  background: var(--shell-strong);
  border: 1px solid var(--border-strong);
  border-radius: var(--radius-small);
  padding: 4px;
}
.app-shell__locale :deep(.el-dropdown-menu__item) {
  color: var(--shell-muted);
  font-size: 13px;
  line-height: 30px;
  border-radius: var(--radius-small);
  display: flex;
  align-items: center;
  gap: 6px;
}
.app-shell__locale :deep(.el-dropdown-menu__item:not(.is-disabled):hover),
.app-shell__locale :deep(.el-dropdown-menu__item:not(.is-disabled):focus) {
  background: var(--accent);
  color: var(--shell-text);
}
.app-shell__locale-check {
  flex: 0 0 14px;
  width: 14px;
  height: 14px;
}
.app-shell__theme-select :deep(.el-select__wrapper) {
  background: var(--shell-strong);
  box-shadow: 0 0 0 1px var(--border-strong) inset !important;
}
.app-shell__theme-select :deep(.el-select__selected-item),
.app-shell__theme-select :deep(.el-select__caret) { color: var(--shell-text); }
.app-shell__main {
  height: calc(100% - 64px);
  overflow: auto;
  padding: var(--page-padding);
}
@media (max-width: 1080px) {
  .app-shell__header { gap: 12px; }
  .app-shell__telemetry-item { display: none; }
  .app-shell__theme-select { width: 128px; }
}
@media (max-width: 720px) {
  .app-shell__header { align-items: flex-start; flex-wrap: wrap; padding: 10px 12px; }
  .app-shell__nav { order: 3; flex-basis: 100%; }
  .app-shell__main { padding: 12px; }
  .app-shell__theme-select { margin-left: auto; }
}
</style>

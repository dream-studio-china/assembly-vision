<script setup lang="ts">
// Decision status badge (docs/design/16-edge-dashboard.md 16.4.2): color plus
// text and icon so the state never depends on color vision alone.

import { computed } from "vue";
import { statusPresentation } from "./status";
import type { DecisionStatus } from "./status";

const props = withDefaults(defineProps<{ status: DecisionStatus }>(), {});

const presentation = computed(() => statusPresentation(props.status));
</script>

<template>
  <span class="status-badge" :class="`status-badge--${presentation.tone}`">
    <span class="status-badge__icon" aria-hidden="true">{{ presentation.icon }}</span>
    <span class="status-badge__label">{{ presentation.label }}</span>
  </span>
</template>

<style scoped>
.status-badge {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 2px 10px;
  border-radius: var(--radius-small, 3px);
  font-weight: 600;
  font-size: 13px;
  line-height: 20px;
  border: 1px solid transparent;
}
.status-badge--success {
  color: var(--status-ok, #1b5e20);
  background: var(--status-ok-soft, #e8f5e9);
  border-color: var(--status-ok, #1b5e20);
}
.status-badge--danger {
  color: var(--status-ng, #b71c1c);
  background: var(--status-ng-soft, #fdecea);
  border-color: var(--status-ng, #b71c1c);
}
.status-badge--warning {
  color: var(--status-warning, #e65100);
  background: var(--status-warning-soft, #fff3e0);
  border-color: var(--status-warning, #e65100);
}
.status-badge__icon {
  font-size: 13px;
}
</style>

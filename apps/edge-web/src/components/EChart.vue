<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref, shallowRef, watch } from "vue";
import type { ECharts } from "echarts";
import * as echarts from "echarts";
import { activeTheme } from "../theme";

const props = defineProps<{ option: echarts.EChartsOption }>();

const el = ref<HTMLElement | null>(null);
const chart = shallowRef<ECharts | null>(null);
let observer: ResizeObserver | null = null;

function render(): void {
  if (!el.value) return;
  if (!chart.value) {
    chart.value = echarts.init(el.value, activeTheme.value === "dark" ? "dark" : undefined);
  }
  const style = getComputedStyle(document.documentElement);
  chart.value.setOption({
    backgroundColor: "transparent",
    textStyle: { color: style.getPropertyValue("--text-muted").trim() },
    tooltip: {
      backgroundColor: style.getPropertyValue("--surface-raised").trim(),
      borderColor: style.getPropertyValue("--border").trim(),
      textStyle: { color: style.getPropertyValue("--text").trim() },
    },
  });
  chart.value.setOption(props.option);
}

onMounted(() => {
  render();
  observer = new ResizeObserver(() => chart.value?.resize());
  if (el.value) observer.observe(el.value);
});

onBeforeUnmount(() => {
  observer?.disconnect();
  chart.value?.dispose();
  chart.value = null;
});

watch(activeTheme, () => {
  chart.value?.dispose();
  chart.value = null;
  render();
});

watch(
  () => props.option,
  () => render(),
  { deep: true },
);
</script>

<template>
  <div ref="el" class="echart" />
</template>

<style scoped>
.echart {
  width: 100%;
  height: 260px;
}
</style>

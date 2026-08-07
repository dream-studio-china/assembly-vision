<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref, shallowRef } from "vue";
import type { ECharts } from "echarts";
import * as echarts from "echarts";

const props = defineProps<{ option: echarts.EChartsOption }>();

const el = ref<HTMLElement | null>(null);
const chart = shallowRef<ECharts | null>(null);
let observer: ResizeObserver | null = null;

function render(): void {
  if (!el.value) return;
  if (!chart.value) {
    chart.value = echarts.init(el.value);
  }
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

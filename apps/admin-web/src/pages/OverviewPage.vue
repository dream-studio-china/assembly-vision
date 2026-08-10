<script setup lang="ts">
const scopeLabel = "Pilot organization / Pilot site / Pilot line";
</script>

<template>
  <main class="overview">
    <header>
      <h1>AssemblyVision Central Administration</h1>
      <p class="muted">M1 controlled pilot - overview, history, and review arrive with the central API.</p>
    </header>
    <section class="card">
      <h2>Overview</h2>
      <p>Scope: {{ scopeLabel }}</p>
      <p class="muted">
        This pilot shell is served by the admin-web container. Inspection history and
        review views are delivered with the central M1 API milestones.
      </p>
    </section>
  </main>
</template>

<style scoped>
.overview {
  max-width: 960px;
  margin: 0 auto;
  padding: 2rem;
}

.muted {
  color: #909399;
}

.card {
  background: #fff;
  border: 1px solid #e4e7ed;
  border-radius: 8px;
  padding: 1.5rem;
}
</style>

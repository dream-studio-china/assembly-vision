import { createRouter, createWebHistory } from "vue-router";

export const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: "/", name: "live", component: () => import("../pages/LiveView.vue") },
    { path: "/inspections", name: "inspections", component: () => import("../pages/InspectionsView.vue") },
    {
      path: "/inspections/:id",
      name: "inspection-detail",
      component: () => import("../pages/InspectionDetailView.vue"),
    },
    { path: "/uploads", name: "uploads", component: () => import("../pages/UploadsView.vue") },
    { path: "/health", name: "health", component: () => import("../pages/HealthView.vue") },
    { path: "/configuration", name: "configuration", component: () => import("../pages/ConfigurationView.vue") },
    { path: "/logs", name: "logs", component: () => import("../pages/LogsView.vue") },
  ],
});

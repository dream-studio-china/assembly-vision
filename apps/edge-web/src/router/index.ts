import { createRouter, createWebHistory } from "vue-router";

export const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: "/", name: "operator-dashboard", component: () => import("../pages/OperatorDashboard.vue") },
    { path: "/live", name: "live", component: () => import("../pages/LiveInspection.vue") },
    { path: "/history", name: "history", component: () => import("../pages/HistoryView.vue") },
    { path: "/traceability/:sn", name: "traceability", component: () => import("../pages/TraceabilityView.vue") },
    { path: "/images/:id", name: "images", component: () => import("../pages/ImageViewer.vue") },
    { path: "/statistics", name: "statistics", component: () => import("../pages/StatisticsView.vue") },
    { path: "/device", name: "device", component: () => import("../pages/DeviceStatus.vue") },
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
    { path: "/login", name: "login", component: () => import("../pages/LoginView.vue") },
  ],
});

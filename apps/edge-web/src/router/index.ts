import { createRouter, createWebHistory } from "vue-router";
import { isHttpMode } from "../services/client";
import { useSessionStore } from "../stores/session";

export const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: "/", name: "operator-dashboard", meta: { requiresAuth: true }, component: () => import("../pages/OperatorDashboard.vue") },
    { path: "/live", name: "live", meta: { requiresAuth: true }, component: () => import("../pages/LiveInspection.vue") },
    { path: "/history", name: "history", meta: { requiresAuth: true }, component: () => import("../pages/HistoryView.vue") },
    { path: "/traceability/:sn", name: "traceability", meta: { requiresAuth: true }, component: () => import("../pages/TraceabilityView.vue") },
    { path: "/images/:id", name: "images", meta: { requiresAuth: true }, component: () => import("../pages/ImageViewer.vue") },
    { path: "/statistics", name: "statistics", meta: { requiresAuth: true }, component: () => import("../pages/StatisticsView.vue") },
    { path: "/device", name: "device", meta: { requiresAuth: true }, component: () => import("../pages/DeviceStatus.vue") },
    { path: "/inspections", name: "inspections", meta: { requiresAuth: true }, component: () => import("../pages/InspectionsView.vue") },
    {
      path: "/inspections/:id",
      name: "inspection-detail",
      meta: { requiresAuth: true },
      component: () => import("../pages/InspectionDetailView.vue"),
    },
    { path: "/uploads", name: "uploads", meta: { requiresAuth: true }, component: () => import("../pages/UploadsView.vue") },
    { path: "/health", name: "health", meta: { requiresAuth: true }, component: () => import("../pages/HealthView.vue") },
    {
      path: "/configuration",
      name: "configuration",
      meta: { requiresAuth: true, admin: true },
      component: () => import("../pages/ConfigurationView.vue"),
    },
    {
      path: "/logs",
      name: "logs",
      meta: { requiresAuth: true, admin: true },
      component: () => import("../pages/LogsView.vue"),
    },
    {
      path: "/dev",
      name: "dev",
      meta: { requiresAuth: true, admin: true },
      component: () => import("../pages/DevToolsView.vue"),
    },
    { path: "/login", name: "login", meta: { requiresAuth: false }, component: () => import("../pages/LoginView.vue") },
    { path: "/forbidden", name: "forbidden", meta: { requiresAuth: false }, component: () => import("../pages/AccessDenied.vue") },
  ],
});

router.beforeEach(async (to) => {
  if (!isHttpMode()) return true;
  const session = useSessionStore();
  // Probe the backend once per page load before the first guarded navigation
  // so deep links render with correct permissions (design 16.10).
  if (!session.checked) await session.check();
  if (to.meta.requiresAuth && !session.authenticated) {
    return { name: "login", query: { next: to.fullPath } };
  }
  if (to.meta.admin && !session.admin) {
    return { name: "forbidden" };
  }
  return true;
});

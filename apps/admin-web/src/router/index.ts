import { createRouter, createWebHistory } from "vue-router";

import InspectionDetailPage from "../pages/InspectionDetailPage.vue";
import InspectionsPage from "../pages/InspectionsPage.vue";
import LoginPage from "../pages/LoginPage.vue";
import OverviewPage from "../pages/OverviewPage.vue";

export const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: "/login", name: "login", component: LoginPage },
    { path: "/", name: "overview", component: OverviewPage },
    { path: "/inspections", name: "inspections", component: InspectionsPage },
    {
      path: "/inspections/:id",
      name: "inspection-detail",
      component: InspectionDetailPage,
    },
  ],
});

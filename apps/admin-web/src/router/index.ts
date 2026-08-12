import { createRouter, createWebHistory } from "vue-router";

import DeviceConfigurationsPage from "../pages/DeviceConfigurationsPage.vue";
import InspectionDetailPage from "../pages/InspectionDetailPage.vue";
import InspectionsPage from "../pages/InspectionsPage.vue";
import LoginPage from "../pages/LoginPage.vue";
import ModelDetailPage from "../pages/ModelDetailPage.vue";
import ModelsPage from "../pages/ModelsPage.vue";
import OverviewPage from "../pages/OverviewPage.vue";
import ProductDetailPage from "../pages/ProductDetailPage.vue";
import ProductsPage from "../pages/ProductsPage.vue";
import ReviewsPage from "../pages/ReviewsPage.vue";
import RuleDetailPage from "../pages/RuleDetailPage.vue";
import RulesPage from "../pages/RulesPage.vue";

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
    { path: "/reviews", name: "reviews", component: ReviewsPage },
    { path: "/products", name: "products", component: ProductsPage },
    {
      path: "/products/:id",
      name: "product-detail",
      component: ProductDetailPage,
    },
    { path: "/rules", name: "rules", component: RulesPage },
    {
      path: "/rules/:id",
      name: "rule-detail",
      component: RuleDetailPage,
    },
    { path: "/models", name: "models", component: ModelsPage },
    {
      path: "/models/:id",
      name: "model-detail",
      component: ModelDetailPage,
    },
    {
      path: "/device-configurations",
      name: "device-configurations",
      component: DeviceConfigurationsPage,
    },
  ],
});

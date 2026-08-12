import { createPinia } from "pinia";
import { createApp } from "vue";
import ElementPlus from "element-plus";
import "element-plus/dist/index.css";
import "./styles.css";

import App from "./App.vue";
import i18n, { initializeLocale } from "./i18n";
import { router } from "./router";
import { initializeTheme } from "./theme";

initializeTheme();
initializeLocale();
createApp(App).use(createPinia()).use(router).use(ElementPlus).use(i18n).mount("#app");

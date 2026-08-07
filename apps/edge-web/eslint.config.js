import config from "@assemblyvision/eslint-config";

export default [
  ...config,
  {
    files: ["**/*.vue"],
    rules: {
      "vue/multi-word-component-names": "off",
    },
  },
];

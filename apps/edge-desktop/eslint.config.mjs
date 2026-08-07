import config from "@assemblyvision/eslint-config";

export default [
  ...config,
  {
    files: ["src/**/*.ts"],
    languageOptions: {
      globals: {
        __dirname: "readonly",
        process: "readonly",
      },
    },
  },
];

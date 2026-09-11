import { defineConfig, devices } from "@playwright/test";

/**
 * 本地运行（npm run e2e）会自动起 Vite 开发服务器并代理到 localhost:8000；
 * 在 verify 容器（compose 网络）中设置 PLAYWRIGHT_BASE_URL=http://web:80
 * 后直接访问由 nginx 托管并代理 /api 的构建产物。
 */
const baseURL = process.env.PLAYWRIGHT_BASE_URL ?? "http://localhost:5173";
const useContainerWeb = !!process.env.PLAYWRIGHT_BASE_URL;

export default defineConfig({
  testDir: "./e2e",
  testMatch: /.*\.e2e\.ts$/,
  timeout: 30_000,
  fullyParallel: false,
  workers: 1,
  reporter: [["list"]],
  use: {
    baseURL,
    trace: "retain-on-failure",
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
  webServer: useContainerWeb
    ? undefined
    : {
        command: "npm run dev",
        url: "http://localhost:5173",
        reuseExistingServer: true,
        timeout: 30_000,
      },
});

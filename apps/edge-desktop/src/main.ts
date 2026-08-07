// Electron main process (docs/design/16-edge-dashboard.md: local kiosk/desktop
// shell). The window loads the built edge-web dashboard from disk, or the Vite
// dev server when ELECTRON_DEV=1. Hardened defaults: context isolation, a
// sandboxed renderer, and no node integration. External links open in the OS
// browser and in-app navigation is restricted to the dashboard origin.

import { app, BrowserWindow, Menu, shell } from "electron";
import * as path from "path";
import { resolveLoadTarget } from "./load-target";

const DIST_INDEX = path.join(
  __dirname,
  "..",
  "..",
  "edge-web",
  "dist",
  "index.html",
);

const isDev = process.env.ELECTRON_DEV === "1";
const isKiosk = process.env.ELECTRON_KIOSK === "1";

function createWindow(): BrowserWindow {
  const win = new BrowserWindow({
    width: 1280,
    height: 800,
    minWidth: 1024,
    minHeight: 640,
    show: false,
    autoHideMenuBar: true,
    fullscreen: isKiosk,
    webPreferences: {
      preload: path.join(__dirname, "preload.js"),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
    },
  });

  win.once("ready-to-show", () => win.show());

  // Open external targets in the OS browser; never navigate the shell away.
  win.webContents.setWindowOpenHandler(({ url }) => {
    if (url.startsWith("http://") || url.startsWith("https://")) {
      void shell.openExternal(url);
    }
    return { action: "deny" };
  });
  win.webContents.on("will-navigate", (event, url) => {
    const allowed = isDev
      ? /^http:\/\/(localhost|127\.0\.0\.1):\d+\//.test(url)
      : url.startsWith("file:");
    if (!allowed) event.preventDefault();
  });

  const target = resolveLoadTarget({
    dev: isDev,
    devUrl: process.env.VITE_DEV_SERVER_URL ?? "http://localhost:5173",
    distIndexPath: DIST_INDEX,
  });
  void win.loadURL(target);

  if (isDev) win.webContents.openDevTools({ mode: "detach" });
  return win;
}

void app.whenReady().then(() => {
  if (isKiosk) Menu.setApplicationMenu(null);
  createWindow();

  app.on("activate", () => {
    if (BrowserWindow.getAllWindows().length === 0) createWindow();
  });
});

app.on("window-all-closed", () => {
  if (process.platform !== "darwin") app.quit();
});

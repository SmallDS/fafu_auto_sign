# FAFU Web 前端

React + TypeScript + Vite + Ant Design 管理台。生产构建产物位于 `dist/`，由同一容器中的 FastAPI 提供。

## 本地开发

```powershell
npm install
npm run dev
```

Vite 会将 `/api` 代理到 `http://127.0.0.1:8000`。

## 验证

```powershell
npm test
npm run build
npx playwright install chromium
npm run test:e2e
```

页面包含 `/dashboard`、`/settings`、`/images`、`/history` 与 `/logs`。界面在 768px 以下切换为移动导航，Playwright 会在 360、390、768 和桌面宽度检查核心页面没有横向溢出。

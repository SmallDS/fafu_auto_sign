# FAFU Auto Sign Web 管理台

这是现有自动签到程序的单账号 Web 管理界面。FastAPI、后台调度器和 Ant Design 前端运行在同一个容器中；SQLite、图片和日志统一保存在 `web/data`，重建或重启容器不会丢失。

> 安全提示：管理台没有登录鉴权，Token 和 Server酱 SendKey 以明文保存在 SQLite 中。只能部署在可信局域网，不要直接暴露到公网，也不要提交 `web/data`。

## 启动

在项目根目录执行：

```powershell
docker compose -f web/docker-compose.yml up -d --build
```

打开 <http://localhost:8000>，先上传签到图片，再进入设置页填写 Token 和图片策略。服务仅启动一个 Uvicorn worker，禁止增加副本或水平扩容，否则可能重复签到。

查看状态与日志：

```powershell
docker compose -f web/docker-compose.yml ps
docker compose -f web/docker-compose.yml logs -f
```

停止服务：

```powershell
docker compose -f web/docker-compose.yml down
```

`down` 不会删除 `web/data`。如需备份，停止服务后复制整个 `web/data` 目录即可。

## 持久化目录

- `data/app.db`：配置、图片元数据和运行历史
- `data/images/library`：持久图库
- `data/images/latest`：最新图片队列；成功上传到远端后核心程序会消费文件
- `data/logs`：结构化日志及 7 天轮转文件

容器入口会初始化 bind mount 的目录权限，随后以 UID/GID `10001:10001` 启动 Uvicorn；应用进程不会以 root 身份运行。若部署环境显式禁止容器入口调整权限，请预先将宿主机 `web/data` 授权给该 UID/GID。

## 旧配置导入

数据库首次初始化时仅导入一次，优先级如下：

1. 环境变量 `FAFU_LEGACY_CONFIG_PATH` 指向的 JSON
2. `/data/import/config.json`
3. 项目根目录 `config.json`

可访问的旧图片会复制到持久图库，原文件不会删除。导入完成后 Web 模式只读取 SQLite。现有 FAFU 明文 HTTP 地址、签名、端点、请求头和参数均未改变，且基础地址不会出现在管理页面或 API 中。

## 本地开发

后端（需先安装项目本身及后端依赖）：

```powershell
python -m pip install -e .
python -m pip install -r web/backend/requirements.txt
$env:FAFU_DATA_DIR = (Resolve-Path web/data)
$env:PYTHONPATH = "src;web/backend"
uvicorn app.main:app --reload --port 8000
```

前端开发服务器由 `web/frontend` 提供。生产镜像会先构建前端，再将 `dist` 复制给 FastAPI 提供静态服务。

测试与构建：

```powershell
python -m pip install -e ".[dev]" -r web/backend/requirements-dev.txt
python -m pytest
Push-Location web/backend; python -m pytest; Pop-Location
Push-Location web/frontend
npm ci
npm test
npm run build
npx playwright install chromium
npm run test:e2e
Pop-Location
```

## 运维约束

- 健康检查只验证 Web 与 SQLite 可用；未配置、暂停或调度异常时仍返回 HTTP 200，并在响应中报告状态。
- 致命签到错误会自动暂停定时 Worker，修复配置后在管理台恢复。
- SQLite 使用 WAL、外键检查和 30 秒 busy timeout。
- 不支持多账号、多副本、高可用或公网安全暴露。

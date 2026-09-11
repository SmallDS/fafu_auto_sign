# FAFU Auto Sign Web 管理台

这是现有自动签到程序的单账号 Web 管理界面。FastAPI、后台调度器和 Ant Design 前端运行在同一个容器中；SQLite、图片和日志统一保存在 `web/data`，重建或重启容器不会丢失。

> 安全提示：管理台没有登录鉴权，Token、测试号 AppSecret 和 OpenID 以明文保存在 SQLite 中。只能部署在可信局域网，不要直接暴露到公网，也不要提交 `web/data`。

## 启动

在项目根目录执行：

```powershell
docker compose -f web/docker-compose.yml up -d --build
```

打开 <http://localhost:8000>，先上传签到图片，再进入设置页填写 Token 和图片策略。

设置页的“用户 Token / Authorization”支持两种输入：直接填写以 2_ 开头的 USER_TOKEN，或粘贴数字 FAFU 请求头中的完整 Base64 Authorization。完整值会由后端严格校验并仅提取、保存末段 USER_TOKEN；原始 Authorization 不会持久化或出现在错误响应中。

服务仅启动一个 Uvicorn worker，禁止增加副本或水平扩容，否则可能重复签到。

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

## 签到任务

Web 自动签到的任务关键词默认为空；空列表不会匹配任何任务，填写一个或多个关键词后才会由后台自动匹配并签到。

管理台的“签到任务”页面直接读取 FAFU 未签到任务分页列表，不受自动签到关键词过滤影响。可查看任务签到位置，并对当前仍在有效时间内的单个任务手动提交签到。提交前服务会重新读取任务来源页确认任务仍有效，随后严格按“详情 → 图片上传 → 签到提交”的既有流程执行。

自动检查、立即检查、任务列表、任务详情和单任务提交共用同一执行槽，任一 FAFU 操作正在进行时其他操作会返回冲突提示；暂停自动检查时仍可浏览或手动提交，完成后保持暂停。任务列表和详情只要求 Token，提交签到还要求图片策略等完整配置。FAFU 鉴权或时间校验失败会暂停自动检查；手动提交失效及上游失败会留下可追踪且已脱敏的运行记录。


## 微信公众号接口测试号通知

设置页可启用微信公众号接口测试号推送。启用前请填写 AppID、AppSecret、模板 ID 和接收人的 OpenID，并在微信公众平台测试号后台创建以下完全匹配的模板：

```text
{{first.DATA}}
任务：{{keyword1.DATA}}
状态：{{keyword2.DATA}}
时间：{{keyword3.DATA}}
{{remark.DATA}}
```

设置读取接口只返回 AppSecret/OpenID 的掩码；密码框留空会保留原值，显式清除任一秘密会自动关闭测试号通道。测试按钮只表示发送任务已提交，不代表微信平台最终送达。access_token 仅在线程安全的进程内缓存中保存，不写入 SQLite 或日志。
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

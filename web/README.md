# FAFU Auto Sign Web 多用户管理台

FastAPI、全局签到队列和 Ant Design 前端运行在同一个容器中。系统使用微信公众号接口测试号 OpenID 识别用户，支持首次管理员扫码绑定、普通用户注册审核、电脑扫码登录、独立签到配置/图片/历史和按 OpenID 模板通知。

## 部署前准备

需要准备：

- 微信公众号接口测试号 AppID、AppSecret 和模板 ID
- 已备案并能访问本服务的公网 HTTPS 地址
- 在测试号“网页授权获取用户基本信息”中只填写公网域名（例如 `sign.example.com`），不要填写协议、端口或 `/auth/wechat/callback` 路径
- 可选的高德 Web JS Key 与 Security JS Code
- 反向代理或负载均衡器负责 HTTPS 终止；应用容器内部仍监听 8000 端口

AppSecret、FAFU Token、CAS 密码、WeLink 刷新令牌和高德 Security JS Code 以明文保存在 SQLite 中，读取接口只返回掩码。请保护 `/data` 备份和服务器权限。

### 微信错误 10003

`10003` 表示 OAuth 的回调域名与测试号后台配置不一致。系统设置中的“公网 HTTPS 地址”应为 `https://sign.example.com` 这样的完整站点来源，而测试号后台“网页授权获取用户基本信息”的授权回调域名只填写 `sign.example.com`。修改系统设置后重新同步菜单；不要填写协议、端口或回调路径。

## 启动与首次初始化

在项目根目录执行：

```powershell
docker compose -f web/docker-compose.yml up -d --build
```

通过公网 HTTPS 地址打开管理台。首次初始化分为两步：

1. 填写并验证测试号、模板、公网地址、菜单名称及可选高德配置。
2. 管理员用微信扫描 5 分钟有效的绑定二维码，通过 `snsapi_userinfo` 获取昵称头像；资料缺失时在手机页面补充。

管理员绑定成功后初始化接口永久关闭，电脑自动换取独立管理员 Session 并进入 `/admin`。初始化没有额外口令，因此全新部署后应立即完成初始化。

## 用户与登录流程

- 公众号菜单指向 `/auth/wechat/start?next=/dashboard`。
- 新用户先经 `snsapi_base` 获取 OpenID，再经 `snsapi_userinfo` 获取昵称头像；资料完成后进入待审核状态。
- 管理员批准后，待审核页面通过 SSE 实时更新并进入 FAFU 首次配置。
- 电脑 `/login` 二维码未扫码 60 秒失效；扫码后活跃用户直接登录，待审核配对最多保留 30 分钟。
- Session 有效期 30 天并滑动续期，每位用户最多保留 10 个有效设备，可在个人中心撤销。
- Cookie 使用 HttpOnly、Secure、SameSite=Lax；写请求同时校验 CSRF Token。

电脑二维码采用“扫码即登录”，不会在手机端二次确认。请只扫描自己主动打开的登录二维码，并通过个人中心检查和撤销陌生设备。

## 管理员功能

管理员导航提供：

- 用户审核、驳回、禁用、恢复、管理员角色调整
- 查看 OpenID、配置完整度、完整 FAFU Token（主动显示会写审计）
- 修改用户配置、撤销设备、立即执行指定用户签到
- 彻底删除用户数据库记录与 `/data/users/{user_id}` 文件
- 修改系统测试号、模板、公网地址、高德和日志设置
- 确认后覆盖并同步公众号自定义菜单
- 查看系统日志和管理员敏感操作审计

系统阻止删除、禁用或降级最后一个有效管理员。

## 多用户调度与数据目录

所有用户共享一个 SQLite 持久任务队列和一个 `SignExecutor` 执行线程：

- 仅调度 `active + worker_enabled + 配置完整` 的用户。
- 手动任务优先于定时任务，同一用户不会重复排入等价任务。
- FAFU 401/408 或致命错误只暂停对应用户。
- 容器重启会把中断的 `running` 任务恢复为 `queued`。
- 不得增加 Uvicorn worker、容器副本或水平扩容，否则可能重复签到。

持久数据：

- `/data/app.db`：系统配置、用户、会话哈希、OAuth state 哈希、配对哈希、队列、图片元数据、历史和审计
- `/data/users/{user_id}/avatar`：用户头像
- `/data/users/{user_id}/images/library`：用户图库
- `/data/users/{user_id}/images/latest`：用户最新图片队列
- `/data/logs`：系统结构化日志

## 从旧单用户版本升级

升级前先停止服务并自行备份整个 `web/data`：

```powershell
docker compose -f web/docker-compose.yml down
Copy-Item -Recurse web/data web/data-backup
docker compose -f web/docker-compose.yml up -d --build
```

`0006` 迁移会：

- 保留测试号 AppID/AppSecret/模板 ID、高德配置和日志级别。
- 清除旧 OpenID、FAFU Token、关键词、图片策略、Worker 状态、图片记录、图片文件、运行历史和旧日志。
- 进入系统配置补全/管理员扫码绑定流程；旧业务数据不提供应用内恢复副本。

`docker compose down` 本身不会删除 bind mount 数据。

## FAFU 签到与地图

个人中心的 FAFU 账号支持两种互斥方式：

- 手动填写 `2_` Token，或粘贴完整 Base64 Authorization；后端严格校验后只保存末段 Token。
- 使用 FAFU 学号、CAS 密码和账号已绑定设备的 `deviceId` 登录；收到短信后在 5 分钟内输入验证码。服务保存凭据和轮换后的 WeLink 刷新令牌，用于后续自动续期。`deviceId` 必须与已绑定设备的 Android ID 精确一致。

新方式连接成功后才替换旧方式；切换到手动方式会删除自动登录凭据。清除 FAFU 配置会删除两种方式的凭据并暂停自动检查。刷新令牌失效时系统只暂停该用户，等待用户在个人中心点击“重新连接”；不会自动发送短信。短信验证码及临时 CAS Cookie 仅保留在进程内，服务重启后需重新发起登录。CAS/WeLink 登录和续期适配自 [Bonger34/fafu-checkin-http](https://github.com/Bonger34/fafu-checkin-http)，许可归属见 [UPSTREAM_LICENSES.md](backend/UPSTREAM_LICENSES.md)。

任务列表、详情和手工提交直接复用原项目的 FAFU 服务，提交仍严格执行“详情 → 图片上传 → 签到”。

FAFU 基础地址固定为原明文 `http://stuhtapi.fafu.edu.cn`。多用户、OAuth 和地图改造没有修改 Authorization 算法、请求头、HTTP 方法、端点、参数位置、上传顺序或签到坐标。

FAFU 坐标固定按 GCJ-02 展示和提交。高德地图仅用于 Marker、逆地理地址、抖动范围和当前位置距离；浏览器当前位置不会保存或用于签到。定位需要 HTTPS 或 localhost。

测试号模板内容：

```text
{{first.DATA}}
任务：{{keyword1.DATA}}
状态：{{keyword2.DATA}}
时间：{{keyword3.DATA}}
{{remark.DATA}}
```

系统 AppID/AppSecret/模板 ID 全局共享，收件 OpenID 自动取当前执行用户，用户可单独关闭通知。

## 运维与验证

```powershell
docker compose -f web/docker-compose.yml ps
docker compose -f web/docker-compose.yml logs -f
```

健康检查只验证 Web 和 SQLite；未初始化、暂停或单用户调度异常不会使容器不健康。

本地验证：

```powershell
$env:PYTHONPATH = "src;web/backend"
python -m pytest
python -m pytest web/backend/tests
Push-Location web/frontend
npm ci
npm test
npm run build
npm run test:e2e
Pop-Location
docker build -f web/Dockerfile .
```

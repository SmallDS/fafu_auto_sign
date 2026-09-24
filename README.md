## 🏫 数字 FAFU 自动签到助手 (FAFU Auto Sign)

![Python 3.10+](https://img.shields.io/badge/Python-3.10+-blue.svg) ![License MIT](https://img.shields.io/badge/License-MIT-green.svg) ![Status Stable](https://img.shields.io/badge/Status-Stable-brightgreen.svg)

本项目是针对福建农林大学与华为 WeLink 合作推出的"数字FAFU" APP 所编写的**自动签到程序**。通过逆向分析其前端加密逻辑，本项目实现了完全脱离 APP 的纯接口级自动化签到。

### ✨ 核心特性

✅ **完美逆向签名算法**：内置已被破解的 `Authorization` 请求头动态加密生成规则（MD5+Base64），无缝伪装官方 APP 请求。

✅ **心跳保活机制 (Keep-Alive)**：通过定时发送轻量级请求，保持后端 Session 存活，**彻底解决 Token 短期过期问题，实现一次抓包，一劳永逸！**

✅ **智能任务识别**：自动遍历任务列表，根据时间戳与自定义关键词精准识别当前有效的签到任务，过滤历史过期任务。

✅ **动态位置获取**：通过任务详情接口自动获取签到位置坐标，**无需手动配置经纬度**，适应不同签到地点。

✅ **防封控策略 (Anti-Ban)**：提交签到时自动为经纬度添加安全范围内的随机偏移量（Float微调），模拟真实人类定位的 GPS 漂移现象。

✅ **自动图片上传**：支持自动读取配置的图片文件，对接七牛云接口实现静默上传与签到绑定。

✅ **多图片随机选择**：支持从指定目录随机选择图片上传，避免长期使用同一张照片被识别，支持 `.jpg`, `.jpeg`, `.png`, `.gif`, `.webp` 格式。

✅ **优雅关闭**：支持 SIGINT (Ctrl+C) 和 SIGTERM 信号优雅退出，确保资源正确释放。

✅ **健壮的重试机制**：客户端内置指数退避重试策略，自动处理网络抖动和临时服务不可用。

✅ **微信推送通知**：支持微信公众号接口测试号模板消息，签到成功/失败实时推送，5分钟内同类型消息自动去重。

### 🚨 免责声明 (Disclaimer)

1. 本项目开源仅为 Python 网络爬虫、JS 逆向工程及自动化测试技术的**学习与学术交流**。
2. 请遵守学校相关管理规定，切勿用于恶意逃避考勤与监管。
3. **使用者因滥用本项目引发的一切后果与责任由使用者本人自行承担，开发者不承担任何直接或间接责任**。

### 🛠️ 快速开始

#### Docker Web 管理台（推荐）

项目提供单容器、多用户 Web 管理台。用户通过微信公众号测试号注册或扫码登录，管理员审核后，每位用户独立维护 FAFU 配置、图片、历史与微信通知；系统使用全局单队列串行签到。数据持久化到 `web/data`。

```powershell
docker compose -f web/docker-compose.yml up -d --build
```

部署公网 HTTPS 反向代理后访问管理台并完成“测试号设置 → 管理员扫码”初始化。AppSecret、FAFU Token 与高德 Security JS Code 以明文保存在 SQLite，API 仅返回掩码；部署、升级和微信回调配置见 [web/README.md](web/README.md)。

Web 的个人中心可选择手动输入 `2_` Token，或通过 FAFU 账号、已绑定设备 ID 和短信验证码连接并自动续期；CAS 密码及 WeLink 刷新令牌同样以明文存储在 `/data/app.db`。Web 可选接入高德地图，在签到任务详情中展示位置、逆地理地址、GPS 随机偏移范围及当前位置距离。地图坐标转换仅用于显示，FAFU 的原始明文 HTTP 请求和签到坐标不会改变。

#### 1. 环境准备

请确保你的电脑或服务器已安装 Python 3.10 或更高版本。

#### 2. 安装

```bash
# 克隆项目
git clone https://github.com/yourusername/fafu_auto_sign.git
cd fafu_auto_sign

# 以可编辑模式安装（推荐开发使用）
pip install -e .

# 或安装生产依赖
pip install .

# 安装开发依赖（如需运行测试）
pip install -e ".[dev]"
```

#### 3. 获取你的专属 USER_TOKEN (需抓包)

由于涉及华为 WeLink 企业级授权，首次使用需手动抓取属于你的 Token：

1. 在手机上安装抓包工具（如 iOS 的 Stream，Android 的 ProxyPin/HttpCanary 或电脑端的 Fiddler/Charles）。
2. 开启抓包，打开"数字FAFU" APP，进入"签到"页面刷新一下。
3. 在抓包记录中找到域名为 `stuhtapi.fafu.edu.cn` 的请求。
4. 查看请求头（Headers）中的 `Authorization` 字段，你会看到一长串字符（如：`MTc3M...`）。
5. 找一个在线 Base64 解码网站，将这串字符解码。解码后长这样：`1773238142:lnccKsR2ovQ4rbQk:c0a6d234c538193226291c5be73c3461:2_6120909285C95C2DA0CA32C6A2AC76CD`
6. **提取以 2_ 开头的最后一段**（即 `2_6120909285C95C2DA0CA32C6A2AC76CD`），这就是你的 USER_TOKEN！

#### 4. 配置

本项目支持多种配置方式，优先级从高到低：

1. **环境变量** (推荐用于生产/容器部署)
2. **`.env` 文件**
3. **JSON 配置文件**
4. **默认值**

##### 方式一：JSON 配置文件

复制配置文件模板并编辑：

```bash
cp config.json.example config.json
```

然后在 `config.json` 的 `"user_token"` 配置项填入你的 USER_TOKEN。

Web 管理台还支持直接粘贴抓包获得的完整 Base64 Authorization；后端校验其 timestamp:nonce:32位十六进制签名:USER_TOKEN 结构后，只保存末段 2_ Token。

##### 方式二：环境变量

设置以下环境变量（适用于 Docker、CI/CD 等场景）：

```bash
export FAFU_USER_TOKEN="2_YOUR_TOKEN_HERE"
export FAFU_JITTER="0.00005"
export FAFU_IMAGE_PATH="dorm.jpg"
export FAFU_BASE_URL="http://stuhtapi.fafu.edu.cn"
export FAFU_HEARTBEAT_INTERVAL="900"
export FAFU_WECHAT_TEST_ENABLED="false"
export FAFU_WECHAT_TEST_APP_ID=""
export FAFU_WECHAT_TEST_APP_SECRET=""
export FAFU_WECHAT_TEST_TEMPLATE_ID=""
export FAFU_WECHAT_TEST_OPENID=""
export FAFU_IMAGE_DIR="./photos/"  # 图片目录路径（启用随机选择）
export FAFU_TASK_KEYWORDS='["晚归"]'  # 任务关键词列表（JSON格式）
export FAFU_LATEST_IMAGE_DIR=""  # 最新图片目录路径
```

**Windows PowerShell:**
```powershell
$env:FAFU_USER_TOKEN="2_YOUR_TOKEN_HERE"
```

#### 5. 配置项说明

| 配置项 | 必需 | 默认值 | 说明 |
|--------|------|--------|------|
| `user_token` | ✅ | - | 用户令牌（必须以 `2_` 开头） |
| `jitter` | ❌ | `0.00005` | GPS 抖动量（0 到 0.001 之间） |
| `image_path` | ❌ | `dorm.jpg` | 签到照片文件路径（当未配置 `image_dir` 或 `latest_image_dir` 时使用） |
| `image_dir` | ❌ | - | 图片目录路径，设置后将从目录中随机选择图片上传（优先级高于 `image_path`） |
| `base_url` | ❌ | `http://stuhtapi.fafu.edu.cn` | API 基础 URL |
| `heartbeat_interval` | ❌ | `900` | 心跳间隔秒数（默认 15 分钟） |
| `log_level` | ❌ | `INFO` | 日志级别（DEBUG/INFO/WARNING/ERROR/CRITICAL） |
| `wechat_test_enabled` | ❌ | `false` | 是否启用微信公众号接口测试号通知 |
| `wechat_test_app_id` | ❌ | - | 测试号 AppID |
| `wechat_test_app_secret` | ❌ | - | 测试号 AppSecret |
| `wechat_test_template_id` | ❌ | - | 测试号模板 ID |
| `wechat_test_openid` | ❌ | - | 接收人的 OpenID |
| `task_keywords` | ❌ | `["晚归"]` | 任务关键词列表，用于识别需要签到的任务（JSON 数组格式） |
| `latest_image_dir` | ❌ | - | 最新图片目录路径，设置后将使用目录中最新修改的图片,图片使用后自动删除 |
💡 **配置示例**：

如果你想使用多图片随机选择功能，可以在 `config.json` 中配置：

```json
{
  "user_token": "2_YOUR_TOKEN_HERE",
  "jitter": 0.00005,
  "image_dir": "./photos/",  // 设置为图片目录路径
  "image_path": "dorm.jpg",   // 备用单图片（可选）
  "base_url": "http://stuhtapi.fafu.edu.cn",
  "heartbeat_interval": 900,
  "log_level": "INFO",
  "task_keywords": ["晚归", "查寝"],  // 自定义任务关键词
  "latest_image_dir": "./camera/"     // 最新图片目录（可选）
}
```

在 `./photos/` 目录中放入多张图片（支持 `.jpg`, `.jpeg`, `.png`, `.gif`, `.webp` 格式），程序每次签到时会随机选择一张上传。

**图片选择优先级**（从高到低）：
1. `latest_image_dir` - 使用目录中最新修改的图片
2. `image_dir` - 从目录中随机选择图片
3. `image_path` - 使用指定的单张图片

**任务关键词说明**：
- 默认只识别包含"晚归"的签到任务
- 可自定义多个关键词，如 `["晚归", "查寝", "点名"]`
- 只要任务名称包含任意一个关键词，就会被识别为待签到任务

#### 微信公众号接口测试号通知（可选）

可在 Web 设置页或 JSON/环境变量中独立启用。请在微信公众平台测试号后台创建内容完全匹配的模板：

```text
{{first.DATA}}
任务：{{keyword1.DATA}}
状态：{{keyword2.DATA}}
时间：{{keyword3.DATA}}
{{remark.DATA}}
```

启用前必须同时配置 AppID、AppSecret、模板 ID 和接收人的 OpenID。AppSecret、OpenID 和 access_token 不会出现在 API 响应或错误日志中；但 AppSecret/OpenID 与其他运行密钥一样以明文持久化，请勿提交配置文件或数据库。
#### 6. 运行

```bash
# 使用默认配置文件 (config.json)
python -m fafu_auto_sign

# 指定配置文件路径
python -m fafu_auto_sign --config /path/to/config.json
# 或简写
python -m fafu_auto_sign -c /path/to/config.json

# 使用环境变量（不指定配置文件）
python -m fafu_auto_sign

# 使用控制台脚本（安装后）
fafu-auto-sign
```

💡 **建议**：由于本程序自带"心跳保活"机制（默认每 15 分钟运行一次），建议将其部署在 24 小时开机的云服务器、树莓派或软路由上。在 Linux 下可使用 `nohup` 命令使其在后台持续运行：

```bash
nohup python -m fafu_auto_sign > sign.log 2>&1 &
```

或使用 systemd 服务（推荐用于生产环境）。

### 🔬 技术内幕 (How it works)

对于爱好技术的同学，本脚本的核心难点在于攻破系统的接口安全校验。

API 使用的 Authorization 并非简单的 JWT，而是一种基于时间的动态签名，其逆向还原逻辑如下：

1. 取 URL 的路径部分（剔除 Query 参数）。
2. 生成当前**精确到秒的 Unix 时间戳** (`Timestamp`)。
3. 生成 16位 随机字符串 (`Nonce`)。
4. 通过 ADB 使电脑连接到手机，安装 LSPosed 模块 Layout Inspect（**需要手机已 ROOT**）启用调试浏览器，运用谷歌或 Edge 浏览器的 chrome://inspect 功能提取前端 JavaScript 代码中硬编码的密钥盐值。
5. 将上述参数拼接：`Secret + URL + Timestamp + Nonce`，计算 **MD5** 哈希值作为签名 (Sign)。
6. 最后将 `Timestamp:Nonce:Sign:UserToken` 通过 Base64 编码，生成最终合法的 Header 头部。

此逻辑已在 `generate_auth_header()` 函数中完美用 Python 复现。

### 🧪 运行测试

本项目包含完整的单元测试和集成测试套件：

```bash
# 运行所有测试
pytest

# 运行测试并生成覆盖率报告
pytest --cov=fafu_auto_sign --cov-report=html

# 运行特定测试文件
pytest tests/test_crypto.py
pytest tests/test_task_service.py
```

### 📁 项目结构

```
fafu_auto_sign/
├── src/
│   └── fafu_auto_sign/
│       ├── __init__.py          # 包初始化
│       ├── __main__.py          # 模块入口点
│       ├── main.py              # 主应用程序逻辑
│       ├── config.py            # 配置管理（Pydantic）
│       ├── client.py            # HTTP 客户端（带重试）
│       ├── crypto.py            # 签名算法实现
│       ├── graceful_shutdown.py # 优雅关闭处理器
│       ├── logging_config.py    # 日志配置
│       └── services/
│           ├── __init__.py
│           ├── task_service.py  # 任务管理
│           ├── sign_service.py  # 签到提交
│           ├── upload_service.py # 图片上传
│           └── notification_service.py  # 微信推送通知
├── tests/                       # 测试套件
├── config.json.example          # 配置文件模板
├── pyproject.toml               # 项目元数据和依赖
└── README.md                    # 本文档
```

### 🤝 参与贡献

欢迎提交 Issue 和 Pull Request！如果你发现了接口变更或开发了新增功能，非常欢迎一起完善本项目。

1. Fork 本仓库
2. 创建你的特性分支 (`git checkout -b feature/AmazingFeature`)
3. 提交你的更改 (`git commit -m 'Add some AmazingFeature'`)
4. 推送到分支 (`git push origin feature/AmazingFeature`)
5. 开启一个 Pull Request

### 📄 开源协议 (License)

本项目采用 **MIT License** 开源协议。

---

***If you find this project helpful, please give it a ⭐️!***

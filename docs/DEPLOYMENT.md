# 启动、配置与维护

## 本地启动

需要 Docker Engine / Desktop（Linux 容器）和 Docker Compose v2.24.4+。只启动本项目，不操作其他容器。

```sh
cp .env.example .env
# 编辑 .env 中模型配置；暂不填可启动账号、笔记本和文件功能，资料理解会明确失败。
docker compose up -d --build
docker compose ps
```

Windows PowerShell 用 `Copy-Item .env.example .env` 复制配置。首次构建需要下载镜像、Python/npm 依赖。若本机镜像加速源不可用，可从可信官方仓库预拉取对应镜像，不需要改变产品代码。MinIO 镜像通过 `MINIO_IMAGE` 可覆盖；见 README 的维护说明。

访问 `http://localhost:3000`；API 文档 `http://localhost:3000/api/docs`，就绪检查 `/api/ready`。`migrate` 服务自动执行 `alembic upgrade head`，成功才启动后端与 Worker。首次 API 启动创建私有桶，不设置公开桶策略。

```sh
docker compose logs -f --tail=100 api worker beat web
docker compose stop
docker compose start
docker compose down
```

`stop` 和 `down` 都保留命名数据卷；**不要对有用数据执行 `down -v`**。数据库、Redis 与文件分别存于 `postgres-data`、`redis-data`、`minio-data`。Worker 处理后前端 4 秒刷新状态；任务调度最多约等待 10 秒。

手动迁移：`docker compose run --rm migrate`。升级前先备份，再构建并启动。不能把修改 ORM 当成自动迁移；后续结构调整新增 Alembic 版本。原始 `001` 快照不得随意改写。

## 模型配置

配置都在服务端，两个模型可属于不同供应商、使用不同账号和密钥：

| 配置 | 含义 |
|---|---|
| CHAT_API_KEY / CHAT_BASE_URL / CHAT_MODEL | 流式 Chat Completions；Base URL 一般含 `/v1` |
| CHAT_TEMPERATURE / CHAT_MAX_TOKENS | 默认 0.1 / 8192 |
| CHAT_SEND_USAGE | 供应商不支持 `stream_options` 时设为 false |
| EMBEDDING_API_KEY / EMBEDDING_BASE_URL / EMBEDDING_MODEL | 独立的 Embeddings 接口 |
| EMBEDDING_DIMENSIONS | 必须与模型实际输出一致，默认 1024 |
| EMBEDDING_SEND_DIMENSIONS | 不支持 dimensions 入参的供应商设为 false |
| EMBEDDING_BATCH_SIZE | 默认 10，兼容 text-embedding-v4 每批最多 10 条的限制 |
| WRITING_MAX_CONTEXT_CHARS / WRITING_MAX_TOKENS | 导读 / 总结的证据正文预算与输出上限，默认 24000 / 4096 |
| LEARNING_MAX_TOKENS | 学习结构化生成输出预算，默认 16384；复核也采用该预算，供应商需支持对应上限 |
| MODEL_TIMEOUT_SECONDS | 单次连接/读取超时，默认 60 秒 |
| GENERATION_TIMEOUT_SECONDS | 整轮回答总时限，默认 180 秒 |
| RETRIEVAL_MAX_DISTANCE | 余弦距离最大阈值，默认 0.55 |

示例配置给出了国内服务常见兼容端点名称，需要自行确认当前账号支持的模型与参数并填入有效密钥。修改配置后：`docker compose up -d --force-recreate api worker beat`。

更换 Embedding 端点、模型或维数后，旧资料向量不会与新模型混用；第一版需删除并重新上传相关资料以重新建立向量。对话模型可独立更换。没有密钥时不返回固定假答案，不开启测试模型。

## 原生开发

```sh
docker compose -f compose.yaml -f compose.dev.yaml up -d db redis minio
cd backend
python -m venv .venv
# 激活虚拟环境，然后安装
pip install -r requirements.txt
```

开发进程需设置 `DATABASE_URL=postgresql+psycopg://narcissus:narcissus_dev_password@localhost:5432/narcissus`、`REDIS_URL=redis://:narcissus_dev_redis@localhost:6379/0`、`S3_ENDPOINT=http://localhost:9000` 及其余模型配置。运行 `alembic upgrade head` 后，在独立终端分别运行：

```sh
uvicorn app.main:app --reload --port 8000
celery -A app.tasks.celery worker --loglevel=INFO --concurrency=2
celery -A app.tasks.celery beat --loglevel=INFO
# frontend 目录
npm ci
npm run dev
```

Windows 原生 Celery 不支持 prefork/time-limit 的完整语义，因此正式处理链路和验证以 Linux Docker Worker 为准，不要用 Windows solo Worker 替代生产部署。浏览器同域转发的 `BACKEND_URL` 默认 `http://localhost:8000`。

## 生产部署

默认 Compose 只把 web 暴露到 `127.0.0.1:3000`，DB、Redis、S3、后端均不公开端口。在 Linux 主机用 Caddy/Nginx 终止 HTTPS，示例在 `deploy/Caddyfile.example`。设定真实域名与 `PUBLIC_ORIGIN=https://你的域名`，配置 DNS 和证书；流式接口关闭缓冲，反向代理总超时至少 200 秒，限制请求体 210763776 字节（201MiB，含表单开销）；单份 PDF 上限 200MiB（界面简写 200MB）。

设置 `ENVIRONMENT=production`，随机生成至少 32 字符的 `APP_SECRET`，替换 PostgreSQL、Redis、MinIO 密码和访问密钥，填入实际模型密钥。生产启动校验会拒绝开发密钥、HTTP origin 或缺少模型配置。数据库密码用于 URL，建议使用随机十六进制字符避免 URI 转义问题。文件服务的 `S3_ACCESS_KEY/S3_SECRET_KEY` 必须与 MinIO 账号一致；生产推荐专用、只可访问项目私有桶的 IAM 账号而非 root。

可将 `S3_ENDPOINT/S3_REGION/S3_BUCKET` 和密钥替换成国内 S3 兼容存储。桶必须私有，后端通过鉴权转发文件，不把预签名公开链接交给浏览器。生产不应同时运行无用的本地 MinIO，按部署环境覆盖 Compose 依赖。对象存储适配当前采用 path-style，需选择兼容该寻址方式的服务。

单机起步建议 4 核 / 8GB，给 PDF Worker 设置资源限制；使用稳定持久磁盘并配置备份。不要公开 Swagger/管理 CLI 到非必要人群。邮件验证、密码找回、管理员后台、审计导出与商业合规流程未包含在此版，正式面向公众开放前需根据运营条件补齐。资料和问题会发送至所配置的模型服务，需选定符合业务数据要求的供应商并在产品隐私政策中明确。

## 备份与恢复

提供 `scripts/backup.sh` 和 `scripts/restore.sh`。在 Linux 或 WSL 的项目根目录运行：

```sh
sh scripts/backup.sh backups/2026-09-29
# 在配置好相同 APP_SECRET 和存储配置的新环境恢复；确认目标数据库可被替换后运行：
sh scripts/restore.sh backups/2026-09-29
```

备份期间停止 web/api/worker/beat，保持 DB/Redis/MinIO 在线，避免跨存储快照不一致。脚本保存 PostgreSQL 自定义格式备份和全部原始文件及其元数据清单；Redis 队列不备份，任务以 DB 记录为准，重启后自动恢复。`.env` 不打包到业务备份，必须另行加密保管，否则原会话哈希、模型访问和存储凭证无法恢复。定期在独立环境进行恢复演练。

恢复目标应为本产品的专用数据库/桶；脚本会替换数据库结构，原桶若含无关对象不会主动删除，恢复后应单独核对容量及遗留对象。备份文件含用户私密文档，需限制权限并按业务要求加密。

## 故障排查

- 页面提示错误：记录响应中的 `X-Request-ID`，在 API 日志搜索同一标识。
- 资料等待：检查 Beat/Worker、Redis、`jobs` 表的调度记录；模型未配置时界面会说明。
- 处理失败：检查任务 ID 对应日志及 `jobs.error/attempts/usage`，不要把私密全文贴入日志。
- 文件删除失败：列表“文件清理记录”中重试，或 `docker compose exec api python -m app.admin retry-cleanup`。
- 回答一直生成：总时限与扫描器会将过期状态纠正为失败；检查模型读超时和反向代理缓冲。
- 重启后无法登录：确认数据卷、`APP_SECRET` 和数据库配置未被替换。

## 自动验证

```sh
# 测试项目独立数据卷及 3100 端口，只有该覆盖文件才配置协议测试模型。
docker compose -p narcissus-test -f compose.yaml -f compose.test.yaml up -d --build
docker compose -p narcissus-test -f compose.yaml -f compose.test.yaml run --rm tester
```

该测试模型用于验证接口传输与引用边界，输出带“测试协议返回”标识，不验证真实生成质量。真实中文问答验收仍需填写正式密钥、上传目标文档，检查多轮追问、无依据问题和引用内容的语义一致性。

## 第二版升级和模型组合

沿用已有 `.env`，不要用示例覆盖已配置的密钥或数据库密码。先按前文备份，停止 web/api/worker/beat，再执行 `docker compose up -d --build`。迁移服务自动从 002 升级到 003，新增笔记、引用快照和生成任务表。已有 ready 资料会被后台补建导读，因此升级后会产生相应模型调用。回退版本应使用升级前的成套数据库 / 文件备份，不能直接删除新表来保留第二版内容。

当前真实验收组合：

```dotenv
CHAT_BASE_URL=https://api.stepfun.com/v1
CHAT_MODEL=step-3.5-flash
CHAT_API_KEY=在本机私有.env填写
EMBEDDING_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
EMBEDDING_MODEL=text-embedding-v4
EMBEDDING_DIMENSIONS=1024
EMBEDDING_SEND_DIMENSIONS=true
EMBEDDING_BATCH_SIZE=10
EMBEDDING_API_KEY=在本机私有.env填写
```

百炼控制台若提供北京工作空间专用 `https://ws-你的工作空间.cn-beijing.maas.aliyuncs.com/compatible-mode/v1`，用控制台给出的完整地址替换通用地址，并配套使用同一工作空间的密钥。两家密钥独立；示例与交付压缩包不含真实密钥。本地 `.env` 只给服务端容器使用。

导读 / 总结故障检查 `generation_jobs.status/error/attempts/usage`，日志中的 task_id 可定位任务。失败会保留真实错误状态；修改或删除来源导致取消时，请重新选择来源生成。人工编辑后的总结是用户文档，引用快照不能为修改后新增的事实背书。

备份工具自动枚举业务表，第二版新增表随 PostgreSQL 备份保存；引用快照也在数据库中，原 PDF 仍在对象存储。新版本无需新增基础服务。

## 第三版升级

沿用原 `.env` 和数据卷，**不要覆盖现有配置**。先备份 PostgreSQL 和原始对象，停止应用写入，再在项目根目录执行：

```sh
docker compose stop web api worker beat
docker compose up -d --build
docker compose exec api alembic current
```

应显示 `004 (head)`。迁移自动依次执行至004；003→004只增加学习成果、闪卡进度、测验尝试表及消息上下文字段，不改写已有业务行。首次安装同一命令会执行完整迁移。不额外部署服务，也不自动为旧资料生成学习内容。

旧 `.env` 缺少 `LEARNING_MAX_TOKENS` 时自动采用16384，可按供应商能力设置，但过小可能截断较多节点的结构化输出。`GENERATION_TIMEOUT_SECONDS=180` 覆盖一次学习生成、可选引文修复及复核（包括逐题审核）的总时限；Worker软/硬时限240/270秒，任务租约300秒。不要随意把模型时限增加到Worker硬限制以上。

后台任务表为 `learning_sets`：`status/phase/error/attempts/claim/usage` 支持追踪、有限重试和租约恢复。API/Worker 日志包含请求或任务标识，不输出完整资料或密钥。取消和删除通过数据库状态及领取标识阻止迟到结果发布；已经发送到供应商的调用不保证立即中止，可能仍计费。

备份脚本的 PostgreSQL 全库备份包含第三版成果、引用快照、复习进度和全部测验尝试；无需单独导出 Redis 队列。回退应恢复升级前数据库及原始文件备份，执行 Alembic downgrade 会删除第三版数据，不作为常规回退操作。

测试完成后可用 `docker compose -p narcissus-test -f compose.yaml -f compose.test.yaml down` 停止隔离测试栈；不加 `-v`。

测验正常调用量为1次生成、1次独立作答复核，以及每道保留题1次实际引用复核；10题通常共12次调用，最多3路并发。引文修复和自动重试可能增加调用。可通过减少题数控制成本及耗时；供应商自身限流或延迟可能使任务失败，系统不会降级为固定结果。

## 第四版音频升级

从迁移004升至005，新增音频概览、音频版本、分段与对象清理账本。沿用现有卷，先备份后迁移，勿使用 `down -v`。独立配置 `TTS_API_KEY / TTS_BASE_URL / TTS_MODEL`，可选声音与任务上限参见 [.env.example](../.env.example) 和 [音频部署说明](AUDIO.md)。Worker与beat必须一起运行，缺少beat时不会调度新任务或清理文件。音频文件是私有对象，经后端权限校验及同域代理提供Range播放；HTTPS代理应保留Range/Content-Range/Content-Disposition。对象存储备份现有脚本包含全部音频分段与合并文件。


## 第五、六版升级

第五、六版分别对应迁移006、007；**当前第七版迁移头为008**。复用既有 `.env` 和数据卷，先停止写入并备份，再执行 `docker compose up -d --build`；迁移服务自动顺序执行所有尚未应用的迁移，不能跳过006。使用 `docker compose exec api alembic current` 确认008。首次启动也使用相同命令。第七版依赖与新增配置见 [演示文稿与信息图](VISUALS.md)，完整迁移交接见 [项目交接文档](../AGENT_HANDOFF.md)。

006增加多来源与不可变版本快照；007增加联网研究及候选来源表，并扩大处理状态字段，兼容网页/OCR的待确认状态。历史PDF、片段ID及既有成果保留。已有环境不用重建数据库或重新上传PDF。

新增的来源配置、OCR部署边界见 [多来源导入](V5-SOURCES.md)，独立搜索接口与完整研究配置见 [联网研究](V6-RESEARCH.md)。本地已验证沿用StepFun账户的独立搜索接口；部署新环境应填写 `SEARCH_API_KEY`，或者在聊天和搜索均使用官方StepFun地址时显式启用 `SEARCH_REUSE_STEPFUN_KEY=true`。不配置时界面明确提示搜索不可用。

备份脚本现已包含全部来源版本、原始文件及音频对象；候选网页的私有预览保存在数据库中，随全库备份保留。不得只备份当前版本原件。恢复/回退始终使用同一时间点的数据库和对象存储备份。升级前的本地验收备份保留在项目外的私有 `work/backups/pre-v6` 目录，不进入交付压缩包。

实际验证及尚存限制见 [第六版验证记录](V6-VERIFICATION.md)。测试栈使用模拟模型协议，不能把测试结果解释为真实供应商的质量保证。

## 第七版升级

迁移008保留旧数据，新增演示文稿与信息图相关表。后端镜像增加中文字体、Cairo和Node.js，升级须重建API、Worker、Beat和迁移镜像，不能只替换前端。无需新增供应商密钥，复用CHAT_*和EMBEDDING_*；新增VISUAL_*限额与字体配置见[图文生成说明](VISUALS.md)。

## Docker Desktop 模型连接排查

浏览器能联网，不代表容器使用的代理路径可访问模型供应商。若出现 TLS 握手中断，分别检查主机直连、主机代理和应用容器；不要关闭证书验证，也不要把握手错误误判为密钥无效。

本地于2026-10-11定位到：Windows主机直连两家模型服务成功，但系统代理路径握手失败，容器的“System proxy”同样失败。修复在 Docker Desktop → Settings → Resources → Proxies 中进行：保持原有代理地址，在“Bypass proxy settings”中仅加入 `.env` 里 `CHAT_BASE_URL` 和 `EMBEDDING_BASE_URL` 的域名；将 Containers proxy 设为“Same as host proxy”，确保容器继承该排除规则。此次设置立即生效，未重启 Docker，也未改变 Windows 或 Clash 的代理设置。

这是本机的网络配置，不是项目固定依赖。其他部署环境应按实际网络决定是否使用代理和域名排除，不要照搬供应商工作空间域名。排除域名变更前保留原设置；回退时恢复原排除列表和容器代理模式。Docker 设置说明：https://docs.docker.com/desktop/settings-and-maintenance/settings/

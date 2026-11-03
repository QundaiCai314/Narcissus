# 第四版：中文音频概览

## 使用入口

笔记本右侧「工作室 → 音频概览」。选择可用 PDF、关注主题、听众、单人讲解或双人对谈，以及简短 / 标准 / 深入。约 3 / 6 / 10 分钟是目标，不保证生成长度；资料不足不会凑数。

先生成带引用讲稿，逐段核对原文，编辑标题、简介、章节、正文和讲解者，点「保存讲稿」。改动段落明确显示「内容已修改，引用需核对」。保存采用 revision 乐观锁，旧标签页不能覆盖新版本。关闭面板保留本页未保存草稿，刷新前应保存。

点「确认讲稿，生成音频」后分段合成，显示已完成段数，不假造百分比。完成后可播放、按段落跳转、跟随播放看引用，下载 WAV 与此音频对应的 Markdown 讲稿。旧音频对应不可变讲稿快照；继续编辑或重新生成不会改写旧音频。

## 语音服务

沿用已接入的阶跃星辰账号，单独适配真实二进制语音接口 `POST /audio/speech`，默认 `step-tts-mini`。选择原因：普通话、服务端现有账号可用、公开支持的预设声音、可直接返回 WAV。没有将聊天请求冒充语音请求，也不使用浏览器系统朗读。

依据：[阶跃星辰语音 API](https://platform.stepfun.com/docs/zh/api-reference/audio/create-audio)、[语音合成指南及预设声音](https://platform.stepfun.com/docs/zh/guides/developer/tts)。当前适配四种声音：磁性男声、温柔女声、播音男声、经典女声。模型和声音须为服务商实际兼容的组合。

服务端 `.env`：

```dotenv
TTS_API_KEY=填入有语音权限的密钥
TTS_BASE_URL=https://api.stepfun.com/v1
TTS_MODEL=step-tts-mini
TTS_DEFAULT_VOICE=cixingnansheng
TTS_SECOND_VOICE=wenrounvsheng
TTS_TIMEOUT_SECONDS=90
AUDIO_MAX_CHARS=4000
AUDIO_MAX_SEGMENTS=40
AUDIO_MAX_DURATION_SECONDS=1200
AUDIO_USER_CONCURRENCY=2
AUDIO_DAILY_LIMIT=20
```

不配置 TTS 时仍可生成和编辑讲稿，合成接口明确拒绝。密钥独立配置，不自动回退到聊天密钥；本机已按用户授权配置现有账号的语音密钥。所有密钥仅保存在服务端，打包排除 `.env`。

每段最多700字，总量受服务端字符数与40段上限约束。语音请求最多1000字，采用24kHz、单声道、16位PCM WAV；验证格式、非空音频和时长后保存。合并插入350毫秒段间停顿，时间轴由实际采样帧数计算，未使用模型时间戳。不依赖 ffmpeg。当前仅导出 WAV，约每分钟2.9MB。

## 两阶段任务与重试

- 讲稿：queued → generating → draft（待确认），异常为 failed / cancelled。基于现有分散片段与检索；只用原始资料。模型只选择证据编号；后端直接关联真实原文快照，校验编号归属，并用模型复核整篇，再对每段独立调用模型（仅提供该段引用的证据）核对事实支持；一个任务最多自动尝试两次。依据不足不发布。
- 音频：queued → synthesizing → queued（下一段）→ merging → complete。一个任务执行单个段落请求，成功音频落入私有对象存储后继续。完整文件与时间轴同时发布。
- 取消只停止后续调度；已发出的外部请求可能继续并计费，返回的成功片段会保留，但不会自动继续下一段。
- 官方接口未提供本适配可依赖的幂等键或请求状态查询能力。连接建立前失败、明确429拒绝最多尝试三次；读取超时、连接中断、5xx、格式错误或返回后持久化不明，一律标为结果不明，不自动重发。页面要求核查后明确确认可能重复计费才可重试。不保证跨网络故障绝对只计费一次。
- 数据库保存请求编号；同编号同参数直接返回已有任务，冲突参数409。相同讲稿版本、声音、模型、地址的音频（含失败/取消）也会复用，避免绕过不明计费确认。成功分段不重做。工作进程崩溃后按确定性对象键尝试恢复已存分段；无结果则进入不明状态。
- 并发按用户跨笔记本计数，取消但外部请求仍在运行也计入。日上限是UTC+8日历日的讲稿和音频任务申请总数，含手动重试；Redis计数持久化。它不是人民币消费预算；以供应商账单为准。
- 保存字符数、实测时长、可获得的请求标识及模型用量。二进制语音响应没有提供的用量保留 null，不伪造计费值。

## 数据与权限

迁移 `005_audio.py` 新增4张表，保留已有用户数据：

| 表 | 责任 |
|---|---|
| audio_overviews | 笔记本FK、请求幂等键、参数、来源版本、引用快照、可编辑讲稿、revision、讲稿任务租约/错误/用量 |
| audio_renders | 概览FK、请求键、讲稿版本快照、声音与模型、合成状态/用量、合并文件与实测时间轴 |
| audio_segments | 音频FK、唯一顺序编号、段落ID、文本、声音、分段状态/用量/对象键 |
| audio_blobs | 无级联FK的对象清理账本，保留笔记本/概览标识、删除状态、错误和重试时间 |

所有读取、编辑、合成、取消、重试、下载接口由后端验证所属笔记本用户；对象桶保持私有。文件接口支持受保护的HTTP Range。引用只来自选定资料的已验证证据快照，点击时复用原文鉴权接口。

来源删除/变化：保留已完成讲稿、音频和引用快照，标记失效，禁止原文跳转与继续旧任务；重新生成使用当前可用来源。删除概览或整个笔记本：取消任务、阻止旧Worker回写，后台清理原始分段与合并文件；清理失败保留audio_blobs错误并指数退避重试。清理账本不随笔记本级联删除，避免丢失失败记录；可由运维查询数据库追踪。

## API

统一错误仍为项目既有 error 结构。列表使用 offset≥0、limit 1–100、默认30。

- `GET /api/audio/options`：服务是否配置、可选声音与规模上限。
- `GET/POST /api/notebooks/{id}/audio`：分页列表/创建；POST携带request_key、document_ids、mode、length、topic、audience、voice_a、voice_b。
- `GET/PATCH/DELETE /api/audio/{id}`：详情、revision检查后保存、删除。
- `POST /api/audio/{id}/retry|cancel|regenerate`：讲稿任务操作；regenerate新建独立概览，需要新request_key。
- `POST /api/audio/{id}/renders`：确认讲稿版本后合成；request_key、revision、voice_a、voice_b。
- `GET /api/audio-renders/{id}`：状态、完成段数、用量、快照与实测时间轴。
- `POST /api/audio-renders/{id}/cancel|retry`：音频任务；不明结果重试需accept_possible_charge=true。
- `GET /api/audio-renders/{id}/file?download=true`：私有WAV流，支持Range。
- `GET /api/audio/{id}/script.md`：当前已保存讲稿。
- `GET /api/audio-renders/{id}/script.md`：对应音频版本的讲稿。

输入模式 single/duo，length short/standard/deep。完整输入输出见 `/api/docs` 的音频概览分组。

## 升级与启动

先用项目备份脚本同时备份 PostgreSQL 与私有对象，保留 `.env`；不要覆盖旧环境文件。填写上述TTS配置后，在项目目录执行：

```sh
docker compose stop worker beat
docker compose build
docker compose run --rm migrate
docker compose up -d
docker compose logs -f api worker beat
```

迁移只新增表；本轮从004升级005。回退应用前应恢复完整备份，不要在已有音频数据时直接降级删表。域名/HTTPS、外部S3、账户和其他模型配置沿用 [部署文档](DEPLOYMENT.md)。不创建付费云资源、不发布公网。

## 测试

```sh
docker compose -p narcissus-test -f compose.yaml -f compose.test.yaml up -d --build
docker compose -p narcissus-test -f compose.yaml -f compose.test.yaml run --rm --build tester
```

测试栈使用独立数据库、对象存储、Redis和显式模型/语音协议夹具；不会把固定回答或静音音频用于正式服务。真实供应商实测与协议测试分别记录于 [验证报告](V4-VERIFICATION.md)。

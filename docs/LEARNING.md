# 第三版学习模块

沿用 Next.js → 同域 API → FastAPI 模块化单体 → PostgreSQL / pgvector；MinIO 私有原文、Redis / Celery Worker 和 Beat 不变。`learning.py` 负责权限和业务，`learning_generation.py` 负责生成任务，`learning_validation.py` 负责结构与证据校验。原文预览、检索和模型服务复用前两版。

## 数据与一致性

| 结构 | 关联及职责 |
|---|---|
| learning_sets | notebook_id 外键级联；family_id + version 唯一；notebook_id + request_key 唯一。每行是独立版本兼生成任务，保存参数、原始资料版本、模型、领取标识、用量、结果及引用快照。知识点/卡片/题目嵌入有限大小的结果 JSON，用版本内唯一ID关联。 |
| card_progress | set_id / user_id 外键级联且组合唯一；保存状态、顺序、当前位置、筛选模式、随机标志和 revision。删除卡片是当前成果版本内的移除标记，进度同时清理。 |
| quiz_attempts | set_id / user_id 外键级联；user_id + request_key 唯一；previous_id 自关联用于错题轮次。题目ID、草稿和已提交答案存 JSON，提交后不可修改。每次尝试独立保留。 |
| messages.learning_context | 记录可信 set_id / node_id；后端验证所属笔记本、当前来源版本和片段后才允许节点提问。 |

成果按笔记本、版本家族、状态、可调度时间、创建时间建立索引；进度及尝试按成果与用户建立索引。已有001–003迁移保持不变，004只新增结构。

成果采用 queued / running / complete / failed / cancelled；phase 区分阅读资料、生成、证据复核。数据库 outbox 每10秒调度，最多3次尝试；300秒领取租约恢复，240/270秒 Worker 软/硬时限。相同请求键返回同一结果，相同活动参数合并；手动生成新版创建独立行，不覆盖历史。失败或取消后显式重试，不发布任何半成品。

所有状态修改及最终发布检查归属、软删除、来源版本、状态与领取标识。生成时不长期持有数据库锁；发布时锁笔记本和成果。删除资料取消相关运行任务，保留完成成果和必要引用快照；删除笔记本先阻断写入，后随既有文件清理流程级联清理学习表。

资料版本变化时动态标记“资料已更新”；旧版可继续学习和查看快照，不能通过旧节点发起基于失效来源的新对话。资料删除后关闭原文跳转，新的生成禁止使用它。现有产品没有“替换 PDF”界面；版本变化处理已有后端支持，验收通过受控版本变更测试。

## 模型与证据

只取所选可用原始资料，复用受用户/笔记本/来源范围限定的证据检索和分散片段组织；上下文正文预算24000字符，单片段最多1600字符。主题、受众以及其中的笔记观点只作为目标，不作为核实过的事实。指令样例始终是待分析资料。

生成后检查ID、父子关系、根节点、循环、3层/40节点上限、题卡数量、字段长度、不同题目、四个不同选项和唯一答案索引。每个引用必须属于当次后端证据，模型引文必须是对应片段中的逐字子串（只规范化空白及全半角），页码和文件信息均由服务器提供。

合法证据编号但引文不匹配时允许一次有界模型修复，只改对应候选的 refs/quotes，随后完整重跑校验；仍不合格的条目及导图后代拒绝发布。未知证据编号不能借此修复。第二次独立模型调用检查事实支持、歧义、重复、冲突和主题相关性。测验先隐藏标准答案与解释，让复核模型逐项独立作答，后端要求恰好一个选项成立且与生成答案相同；随后每题只携带该题实际引用的片段单独审核答案与解释，避免借用其他题目的证据或附带错误解释；最多3路并发，每题复核输出上限4096，仍受整轮180秒限制。拒绝项移除，导图连带移除失去父节点的后代；全部不合格就失败，数量不足显示说明。复核是同一服务的独立调用，并非异构模型或人工保证。

一次任务整体时限默认180秒，生成预算16384 tokens、复核同样受该预算约束。错误与可获得用量持久化；日志只记录安全错误和任务标识，不记录完整资料或密钥。

## API

沿用 cookie 身份、同域写入校验、统一 `{error:{code,message,request_id}}` 错误。分页返回 `{items,total,limit,offset}`，limit 默认30、最大100。所有资源均由服务端验证用户与笔记本归属，不通过隐藏前端控件实施授权。

| 方法 / 路径（均以 /api 开头） | 说明 |
|---|---|
| GET /notebooks/{id}/learning | 分页列出成果版本，含来源状态、掌握进度、最近测验 |
| POST /notebooks/{id}/learning | kind、document_ids、topic、audience、difficulty、count、request_key(UUID)；返回202 |
| GET /learning/{id} | 状态及完成结果；测验仅题干和选项，不含答案/解释/知识点/证据 |
| POST /learning/{id}/regenerate | request_key；按当前可用来源建立新版本 |
| POST /learning/{id}/cancel、/retry | 取消或重试，共用状态机；取消结果不会迟到发布 |
| GET /learning/{id}/flashcards/progress | 持久化初始化并返回进度 |
| PATCH /learning/{id}/flashcards/progress | revision；可选 card_id/state、current_id、mode(all/review)、shuffle；旧版本409 |
| DELETE /learning/{id}/flashcards/{card_id} | 删除指定卡片并清理其进度 |
| GET /learning/{id}/attempts | 分页历史，不暴露未提交题的答案 |
| POST /learning/{id}/attempts | request_key、mode(all/wrong)、previous_id（仅完成轮次错题） |
| GET /quiz-attempts/{id} | 当前尝试；仅已提交的题有答案、解释、知识点和引用 |
| PATCH /quiz-attempts/{id}/answers/{qid} | selected(0–3)、revision；保存选择，不揭示答案 |
| POST /quiz-attempts/{id}/answers/{qid}/submit | selected、revision；事务锁内判分；相同重复提交幂等，不重复计分 |
| POST /conversations/{id}/ask | 现有问题接口增加可选 learning_context:{set_id,node_id}；服务器确定并覆盖来源范围 |

测验题目使用显式白名单序列化；提交前连原文片段及可能带答案的知识点名称也不返回。只有已提交题目的来源才进入尝试引用列表。成绩通过提交记录计算，全部作答后完成，不依赖客户端正确答案或增量计分。重做可能已经知道旧题答案，这是练习产品，不是封闭考试系统。

进度和作答的 revision 避免不同浏览器的旧请求覆盖新进度；前端保存时禁用冲突操作，409要求重新加载。重做和生成用UUID请求键防止网络重试重复创建。

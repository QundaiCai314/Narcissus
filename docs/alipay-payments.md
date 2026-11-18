# 支付宝会员与额度收款

本实现使用支付宝官方 Python SDK `alipay-sdk-python==3.7.1411`，产品为 **AI 网页应用收款**，同时支持会员单次购买与使用额度充值。未实现自动续费。接口及 SDK 使用方式依据支付宝 AI 付 Skill 的本地契约和当前安装包源码核对。

官方产品资料：[Vibe Pay](https://aipay.alipay.com/docs/vibe-pay.html)、[网页应用接入](https://aipay.alipay.com/docs/vibe-pay/ai-web-app-payment-qianyi/ai-web-app-payment-integration-guide.md)。商户权限、实际费率与审核结果以你的支付宝账号当前显示内容为准。

## 默认状态与数据边界

默认 `ALIPAY_ENABLED=false`、`BILLING_ENFORCE_CREDITS=false`、商品目录为空。不会自动开始向已有用户收费，也不依赖新表来运行原有功能。代码只新增迁移011所列五张计费表；生产迁移须单独审阅和执行，不能通过启动应用自动建表，不能删除或重建既有数据卷。

账号页为 `/billing`，结果页为 `/billing/return`。会员在有效期内免扣配置中的学习生成额度；原有每天、并发、资料与请求上限继续适用。额度成本仅支持本轮接入的测验 `quiz`、思维导图 `mindmap` 与闪卡 `flashcards`；目录核对等本地处理保持原行为。未配置成本的功能不扣额度。

## 配置

将配置保存在本地被 Git 忽略的 `.env`。价格由你决定后填写 `BILLING_PRODUCTS_JSON`，数组每项包含：

| 字段 | 说明 |
| --- | --- |
| id | 唯一商品编号，小写字母、数字或下划线 |
| title | 商品名称，最多80字，不含HTML特殊字符 |
| kind | membership 或 credits |
| amount_cents | 正整数分，1–10000000；不使用浮点元 |
| member_days | 会员天数；额度包必须为0 |
| credits | 赠送或购买的额度数；额度包必须大于0 |

`BILLING_CREDIT_COSTS_JSON` 是各类学习生成的正整数成本映射。确认规则后再启用 `BILLING_ENFORCE_CREDITS=true`。订单保存商品价格与权益快照，后续改价不会改变已有订单。客户端只能提交商品编号与请求幂等键。

### 沙箱

服务器直接读取后端项目根目录 `.alipay-sandbox.json`，使用其 `appIds` 唯一应用的 `appId`、`pid`、`appPrivatePkcsKey`、`alipayPublicKey`，固定使用沙箱网关。不会拷贝、包装、转换或打印私钥。该文件既被 Git 忽略，也从 Docker 构建上下文排除。容器联调须将原文件只读挂载到 `/app/.alipay-sandbox.json`，不打进镜像。

### 生产

由你在设备本地准备同一生产应用的原始 SDK 配置 JSON，包含 `appId`、`sellerId`、`appPrivatePkcsKey`、`alipayPublicKey`。设置 `ALIPAY_PRODUCTION_CONFIG` 为容器中已只读挂载的绝对路径，并显式设置 `ALIPAY_ENVIRONMENT=production`。应用私钥保持非 Java SDK 所需的原始PKCS#1字符串，不加PEM头尾；格式转换由用户使用支付宝官方密钥工具完成。`PUBLIC_ORIGIN` 必须为实际HTTPS站点，回跳地址由它与真实 `/billing/return` 路由组成。

应用ID、商户ID、应用私钥与支付宝公钥必须来自当前应用。不要将生产私钥发给 Agent。签约和应用审核完成、价格确认、迁移011及所选到账确认链路验收完成之后，才可启用生产收款。

## 到账与失败处理

页面支付使用 `page_execute(..., http_method='POST')` 生成HTML表单，在专用页面渲染自动提交。不会把HTML当作URL。回跳页忽略浏览器提供的“支付成功”等参数，只查询当前用户有权访问的订单。

SDK强制RSA2，服务端查询响应必须验签。通知必须为表单，经过完整参数验签、应用/商户/订单/金额比对，排除退款等非付款事件后，才能原子记账。用户行锁、唯一交易号、唯一发放流水及通知事件记录防止并发或重复发放。

`ALIPAY_NOTIFY_URL` 可选。使用时应为已部署、支付宝可访问的真实地址，精确路径为 `/api/billing/alipay/notify`。仅此端点豁免浏览器CSRF头要求，仍强制支付宝签名校验，成功返回纯文本 `success`。没有公网通知地址时不传该参数，由API后台每30秒调度待确认订单，逐步退避查单。关闭浏览器和进程重启不会丢失订单。未知、超时及未付款状态继续保留待确认，不能据此判为支付失败或发放权益。

启用额度扣减后，学习生成的扣费与创建任务在同一事务中；失败或取消的任务幂等退回预留额度，重试任务重新计费。后台也会恢复因资料变更或工作进程中断而取消的任务额度。

## 关单与退款

用户可关闭自己未付款的订单；关闭前先查单，已付订单不能通过关单撤销。代码不会主动对未知真实交易发起关单。

退款仅允许 `BILLING_OPERATOR_EMAILS` 中的管理账号操作。接口明确要求 `{"confirm_full_refund":true}`，不接受客户端退款金额。本版只自动处理全额退款；额度已使用或会员与后续订单叠加时返回人工核对提示，不猜退款政策或部分退款分摊。

退款先持久化原退款号、全额金额和权益预留，重复调用始终复用同一退款号及金额。未知结果保持待确认，不把SDK受理成功当成退款成功；`fund_change=N` 时查退款结果，查询至少间隔10秒。只有核对原订单、交易号、金额和明确资金变化/`REFUND_SUCCESS` 后才显示已退款。待确认期间预留额度不可消费，后台可用原退款号重试。支付宝商家后台手工处理而绕过本接口的退款，需另行人工核对和调整权益。

## 接口

| 方法与路径 | 用途 |
| --- | --- |
| GET /api/billing/catalog | 可购买商品及沙箱标识 |
| GET /api/billing/wallet | 当前用户余额与会员期限 |
| GET /api/billing/learning-quote | 当前账号的学习生成成本与会员减免 |
| POST /api/billing/orders | 创建价格快照订单 |
| GET /api/billing/orders | 当前用户最近订单 |
| GET /api/billing/orders/{id}/pay | SDK支付表单页面 |
| GET /api/billing/orders/{id} | 当前用户订单 |
| POST /api/billing/orders/{id}/refresh | 主动查单确认 |
| POST /api/billing/orders/{id}/close | 关闭未付款订单 |
| POST /api/billing/orders/{id}/refund | 管理账号全额退款 |
| GET /api/billing/refunds/{id} | 退款确认 |
| POST /api/billing/alipay/notify | 支付宝通知 |

`tests/test_billing.py` 使用模拟支付、内存SQLite和专用PostgreSQL验证关键逻辑。`tests/billing_sandbox_server.py` 仅在显式测试标志和专用测试库下启动，不是生产入口。测试中的价格、账号与密钥均为隔离夹具，不能用于真实交易配置。

## 本轮验证记录（2026-11-18）

支付逻辑与独立数据库迁移共32项测试通过，其中包括真实PostgreSQL并发重复到账、010→011升级后保留既有测试用户及笔记本。前端生产构建通过；浏览器检查覆盖会员/额度切换、服务端定价、未开通状态、320/390/768宽度与结果页。

真实SDK表单已在独立沙箱站点检查，核对了精确回跳地址、GET回跳页面、代理后的CSP及自动POST提交。测试拦截了提交至支付宝网关的请求，没有完成付款，不能据此声称实际支付、到账或退款已端到端验证。正式售价、商户开通、生产配置和生产迁移仍待完成。

付款入口使用单独的CSP，只允许支付宝官方网关与SDK指定提交脚本；其他页面继续使用原有策略。生成收费开启后，界面显示本次成本与余额，并在提交前再次确认。不要在没有明确价格、权益、退款规则与用户可见提示的情况下开启额度扣减。

# Narcissus 公网与真实收款上线

GitHub 保存源码，不会自动提供这个完整应用的访问地址。Narcissus 同时需要前端、API、任务进程、PostgreSQL、Redis和对象存储。推荐先部署到支持 Docker 的云服务器，再为域名配置HTTPS。

## 没有地址时的两条路线

1. **正式上线：云服务器＋域名。** 服务器提供公网IP，域名的A记录指向该IP；本仓库的Caddy反向代理自动申请和续期HTTPS证书。部署前再确定服务器预算、地域与域名，不需要预先准备一个现成网址。
2. **临时联调：仅验证指定页面。** Cloudflare Quick Tunnel可为本机生成临时HTTPS地址，但地址会随进程变化、没有可用性保证，而且不支持本项目对话使用的SSE。因此不要把它当作完整项目的正式入口。尚未获得明确授权时，不将本机私有笔记本服务暴露到公网。

官方依据：[Caddy自动HTTPS](https://caddyserver.com/docs/automatic-https)、[Cloudflare Quick Tunnel限制](https://developers.cloudflare.com/tunnel/get-started/quick-tunnels/)。

## 仓库已准备的配置

- `compose.public.yaml`：增加Caddy服务，只对外提供80/443，保持数据库、Redis、MinIO为内部服务；不改变原有数据卷。
- `deploy/Caddyfile`：反代至web容器，及时转发流式响应。
- `compose.billing.yaml`：把用户在本机准备的生产SDK配置只读挂载给API和任务进程，不将私钥打进镜像。
- `backend/billing-launch.json`：首发真实商品与计费规则；`BILLING_PROFILE=launch`选择这套规则，单独选择规则不会开启支付或扣费。

不要将 `.env.example` 覆盖已有 `.env`，不要更改现有 `COMPOSE_PROJECT_NAME=zhiye` 来尝试重用业务数据卷。新云服务器承接原有笔记本时，需要单独安排数据库和MinIO备份、恢复及核对，不能用一个空环境冒充原有数据已迁移。

## 首发价格

| 项目 | 价格或用量 |
| --- | --- |
| 研读月会员 | ¥29.90，30天，不自动续费 |
| 会员学习生成 | 每个账号每天20次免扣额度，测验、导图、闪卡共用；北京时间零点重置 |
| 学习额度包 | ¥9.90，100额度 |
| 非会员生成测验 | 每份5额度 |
| 非会员生成导图 | 每份3额度 |
| 非会员生成闪卡 | 每份2额度 |

生成中会预留额度或会员次数；成功保留扣减，失败或取消后幂等返还。会员当日次数用完后阻止继续生成，不会未经确认自动改扣余额。既有并发与请求上限仍适用。

## 实际上线还需完成

1. 用户选定服务器与域名，准备DNS，并确保公网80/443可访问；在本地配置 `NARCISSUS_DOMAIN` 为不带协议的主机名，`PUBLIC_ORIGIN` 为对应的HTTPS源站。
2. 按生产校验要求设置强随机应用、数据库、Redis与对象存储凭据。已有数据库改密码必须与数据库实际账号同步操作，不能只改环境变量。
3. 配置SMTP，完成真实邮箱验证码投递验证；当前无发信服务时新账号注册会保持关闭。
4. 在支付宝官方流程确认产品签约、应用上线和公钥生效。生产私钥由用户自行保存到本地受保护配置，不发给Agent。
5. 将 `ALIPAY_PRODUCTION_CONFIG_HOST` 指向用户本地准备的SDK JSON绝对路径；只有准备好该文件时才使用 `compose.billing.yaml`。绑定文件至少需要让容器中的应用用户有读取权限，不得因此扩大文件的公开权限。
6. **现有业务库先备份、核对当前迁移版本并单独审阅011。** 011只增加五张计费表；本轮未执行生产迁移，也不运行降级或重建数据卷。
7. 依次验证生产配置、商品展示、通知/后台查单与订单归属校验，再由已授权的操作者开启 `ALIPAY_ENABLED=true`、`ALIPAY_ENVIRONMENT=production` 和 `BILLING_ENFORCE_CREDITS=true`。使用真实账号完成付款、到账、重复通知和退款验证后，才能对外宣称真实收款可用。

无公网通知地址时，可以省略 `ALIPAY_NOTIFY_URL`，使用已有服务端后台查单，不因此单独阻断上线；网站回跳源站仍需要正确配置。

## 配置语法验收

可以使用 `docker compose -f compose.yaml -f compose.public.yaml -f compose.billing.yaml config --quiet` 检查合并语法。该检查不启动服务、不校验商户状态，也不证明域名或密钥已准备好。需要提前设置上述主机名和本地文件路径变量，且不要打印包含私密环境变量的完整合并配置。

业务数据服务保持原配置。更新应用时沿用 `--no-deps`，不得执行 `down -v`、删除数据卷或通过更换项目名重新初始化数据。

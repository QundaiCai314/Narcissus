# 邮箱注册与登录

新注册必须提交邮箱收到的6位验证码，并再次确认密码。已有账号登录方式保持不变。

在本地、已被 Git 忽略的 `.env` 配置以下内容，不要将授权码发到聊天或提交到仓库：

```dotenv
SMTP_HOST=smtp.example.com
SMTP_PORT=587
SMTP_SECURITY=starttls
SMTP_USERNAME=your-mailbox@example.com
SMTP_PASSWORD=your-mail-provider-app-password
SMTP_FROM=your-mailbox@example.com
SMTP_TIMEOUT_SECONDS=10
```

供应商使用465端口时，将 `SMTP_SECURITY` 改为 `ssl`。仅接受经过系统证书验证的加密连接，不支持明文降级。发件地址应是服务商授权的邮箱，并按其要求完成域名验证。保存后仅重新创建 `api` 服务以加载环境配置，不需要数据库迁移。

未配置时注册界面提示邮件未开通，发送接口返回503；不会绕过邮箱验证。配置是否齐全由 `/api/auth/registration-options` 提供，连接和实际投递是否成功仍需用自己的邮箱验收。API不返回、日志不记录验证码。验证码10分钟有效、60秒后可重发，重发使旧码失效；同邮箱5次/小时、同IP12次/小时；连续输错5次使该次验证码失效。邮件或Redis不可用时拒绝注册。

验证码与邮箱、随机挑战标识绑定，Redis仅保留HMAC摘要并通过Lua原子消费，无法重复使用。数据库不存验证码。密码使用既有Argon2id哈希；新密码10–128个字符，建议15位以上、避免常见或反复重复的密码。安全性提示仅在浏览器计算，属于参考，不代表破解时间。

隔离测试使用单独Redis和内存SQLite、模拟SMTP传输，不连接生产数据库、不实际发信。真实邮件验收须待配置完成。

## 登录画面

使用柔米纸底、浅蓝与冷棕双墨色；保留复古窗口边框和错位阴影，装饰只留像素窗控与光标。布局为一张主视觉印画与一个账号窗口，宋体标题搭配无衬线表单，采用孔版网点与纸纹质感。主体印画由图像模型生成，HTML文字独立排版以保留可读性与响应式布局。

配色与节奏参考已安装的 [mono-color skill](https://github.com/yanliudesign/mono-color-skill)，版本 `c8ff70597ddedcd65f21a0b528f6a70c35690b0a`。用户指定配色覆盖技能默认值。图像提示词见 `docs/auth-art-prompt.txt`。

"""Encrypted SMTP delivery and single-use, email-bound Redis verification codes."""
import secrets
import smtplib
import ssl
import uuid
from email.message import EmailMessage
from email.utils import formataddr
from email_validator import validate_email, EmailNotValidError
from .config import settings
from .security import redis, digest, rate_limit
from .errors import fail

TTL = 600
COOLDOWN = 60
MAX_ATTEMPTS = 5

RESERVE = """
if redis.call('EXISTS', KEYS[2]) == 1 then return redis.call('TTL', KEYS[2]) end
redis.call('SET', KEYS[2], ARGV[1], 'EX', ARGV[3])
redis.call('DEL', KEYS[1])
redis.call('HSET', KEYS[1], 'id', ARGV[1], 'digest', ARGV[2], 'attempts', 0, 'state', 'pending')
redis.call('EXPIRE', KEYS[1], ARGV[4])
return -1
"""
ACTIVATE = """
if redis.call('HGET', KEYS[1], 'id') ~= ARGV[1] or redis.call('HGET', KEYS[1], 'state') ~= 'pending' then return 0 end
redis.call('HSET', KEYS[1], 'state', 'active')
redis.call('EXPIRE', KEYS[1], ARGV[2])
return 1
"""
CANCEL = """
if redis.call('HGET', KEYS[1], 'id') == ARGV[1] then redis.call('DEL', KEYS[1]) end
if redis.call('GET', KEYS[2]) == ARGV[1] then redis.call('DEL', KEYS[2]) end
return 1
"""
CONSUME = """
if redis.call('HGET', KEYS[1], 'id') ~= ARGV[1] or redis.call('HGET', KEYS[1], 'state') ~= 'active' then return 0 end
if redis.call('HGET', KEYS[1], 'digest') ~= ARGV[2] then
 local attempts = redis.call('HINCRBY', KEYS[1], 'attempts', 1)
 if attempts >= tonumber(ARGV[3]) then redis.call('DEL', KEYS[1]); return -2 end
 return -1
end
redis.call('HSET', KEYS[1], 'state', 'used')
redis.call('HDEL', KEYS[1], 'digest')
return 1
"""


def configured():
    config = settings()
    if not all((config.smtp_host, config.smtp_from, config.smtp_username, config.smtp_password)):
        return False
    if not 1 <= config.smtp_port <= 65535 or not 1 <= config.smtp_timeout_seconds <= 30:
        return False
    try:
        validate_email(config.smtp_from, check_deliverability=False)
    except EmailNotValidError:
        return False
    return not any('\r' in item or '\n' in item for item in (config.smtp_host, config.smtp_from))


def keys(email):
    identity = digest('registration-email:' + email)
    return 'registration:code:' + identity, 'registration:cooldown:' + identity


def code_digest(email, challenge_id, code):
    return digest('registration-code:' + email + ':' + challenge_id + ':' + code)


def evaluate(script, key_list, *args):
    try:
        return int(redis.eval(script, len(key_list), *key_list, *args))
    except Exception:
        fail(503, 'verification_unavailable', '验证码服务暂不可用，请稍后重试')


def send_message(email, code):
    config = settings()
    message = EmailMessage()
    message['Subject'] = 'Narcissus 注册验证码'
    message['From'] = formataddr(('Narcissus', config.smtp_from))
    message['To'] = email
    message.set_content(f'你的注册验证码是：{code}\n\n验证码10分钟内有效。请勿将验证码告诉他人。\n如果不是你本人申请，请忽略这封邮件。')
    context = ssl.create_default_context()
    if config.smtp_security == 'ssl':
        client = smtplib.SMTP_SSL(config.smtp_host, config.smtp_port, timeout=config.smtp_timeout_seconds, context=context)
    else:
        client = smtplib.SMTP(config.smtp_host, config.smtp_port, timeout=config.smtp_timeout_seconds)
    with client:
        if config.smtp_security == 'starttls':
            client.ehlo()
            client.starttls(context=context)
            client.ehlo()
        client.login(config.smtp_username, config.smtp_password)
        rejected = client.send_message(message)
        if rejected:
            raise RuntimeError('Recipient rejected')


def issue(email, ip):
    if not configured():
        fail(503, 'mail_unavailable', '注册验证码暂时无法发送，请稍后再试；已有账号可正常登录')
    rate_limit('registration-code-ip:' + ip, 12, 3600)
    rate_limit('registration-code-email:' + email, 5, 3600)
    challenge_id = uuid.uuid4().hex
    code = f'{secrets.randbelow(1000000):06d}'
    key, cooldown_key = keys(email)
    delay = evaluate(RESERVE, [key, cooldown_key], challenge_id, code_digest(email, challenge_id, code), COOLDOWN, TTL)
    if delay >= 0:
        fail(429, 'code_cooldown', '验证码已发送，请60秒后再试')
    try:
        send_message(email, code)
    except Exception:
        evaluate(CANCEL, [key, cooldown_key], challenge_id)
        fail(503, 'mail_delivery_failed', '邮件发送未成功，请稍后重新获取验证码')
    if evaluate(ACTIVATE, [key], challenge_id, TTL) != 1:
        fail(409, 'code_replaced', '验证码状态已改变，请重新获取')
    return dict(challenge_id=challenge_id, expires_in=TTL, retry_after=COOLDOWN,
                message='验证码已提交发送，请查收邮箱并留意垃圾邮件。')


def consume(email, challenge_id, code):
    key, _ = keys(email)
    result = evaluate(CONSUME, [key], challenge_id, code_digest(email, challenge_id, code), MAX_ATTEMPTS)
    if result != 1:
        message = '尝试次数过多，请重新获取验证码' if result == -2 else '验证码错误、已过期或已使用，请检查或重新获取'
        fail(422, 'invalid_verification_code', message)

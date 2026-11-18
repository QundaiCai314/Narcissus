"""Local sandbox post-validation: outputs booleans, never key material."""
import json
from pathlib import Path
from app.config import settings
from app.alipay_gateway import AlipayGateway, PROJECT_ROOT, SANDBOX_GATEWAY


def main():
    config = settings()
    if not config.alipay_enabled or config.alipay_environment != 'sandbox':
        raise RuntimeError('Explicit sandbox configuration required')
    path = PROJECT_ROOT / '.alipay-sandbox.json'
    raw = json.loads(path.read_text(encoding='utf-8-sig'))['appIds'][0]
    gateway = AlipayGateway()
    loaded = gateway.config
    checks = {
        'project_file_is_regular': path.is_file() and not path.is_symlink(),
        'sandbox_gateway': loaded.gateway == SANDBOX_GATEWAY,
        'app_id_field': loaded.app_id == raw['appId'],
        'seller_field': loaded.seller_id == raw['pid'],
        'python_pkcs1_field_unchanged': loaded.app_private_key == raw['appPrivatePkcsKey'],
        'verification_public_key_unchanged': loaded.alipay_public_key == raw['alipayPublicKey'],
        'return_route': loaded.return_url == config.public_origin.rstrip('/') + '/billing/return',
        'sdk_initialized': gateway.client is not None,
    }
    if not all(checks.values()):
        raise RuntimeError('Sandbox post-validation failed')
    print(json.dumps(checks))


if __name__ == '__main__':
    main()

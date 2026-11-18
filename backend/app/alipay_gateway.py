"""Official SDK adapter. Keys are read on the server and never returned or logged."""
import json
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit
from .config import settings

SANDBOX_GATEWAY = 'https://openapi-sandbox.dl.alipaydev.com/gateway.do'
PRODUCTION_GATEWAY = 'https://openapi.alipay.com/gateway.do'
PROJECT_ROOT = Path(__file__).resolve().parents[1]


class PaymentUnavailable(Exception):
    pass


class ProviderUnavailable(Exception):
    pass


@dataclass(frozen=True)
class PaymentConfig:
    app_id: str
    seller_id: str
    environment: str
    gateway: str
    return_url: str
    notify_url: str
    app_private_key: str = field(repr=False)
    alipay_public_key: str = field(repr=False)


def load_config():
    s = settings()
    if not s.alipay_enabled:
        raise PaymentUnavailable('支付尚未开通')
    try:
        if s.alipay_environment == 'sandbox':
            # This is the exact project file verified by the Alipay Skill.
            path = PROJECT_ROOT / '.alipay-sandbox.json'
            if path.is_symlink():
                raise ValueError('Sandbox configuration must be a regular project file')
            data = json.loads(path.read_text(encoding='utf-8-sig'))
            apps = data['appIds']
            if not isinstance(apps, list) or len(apps) != 1:
                raise ValueError('A single validated sandbox app is required')
            app = apps[0]
            app_id, seller_id = app['appId'], app['pid']
            private, public = app['appPrivatePkcsKey'], app['alipayPublicKey']
            gateway = SANDBOX_GATEWAY
        else:
            path = Path(s.alipay_production_config)
            if not path.is_absolute() or path.is_symlink():
                raise ValueError('Protected absolute production configuration required')
            data = json.loads(path.read_text(encoding='utf-8-sig'))
            app_id, seller_id = data['appId'], data['sellerId']
            private, public = data['appPrivatePkcsKey'], data['alipayPublicKey']
            gateway = PRODUCTION_GATEWAY
        if not all(isinstance(v, str) and v and v == v.strip() for v in (app_id, seller_id, private, public)):
            raise ValueError('Incomplete configuration')
        if not app_id.isdigit() or not seller_id.isdigit() or '-----' in private or '-----' in public:
            raise ValueError('Raw SDK key fields and valid identifiers required')
        origin = s.public_origin.rstrip('/')
        parsed = urlsplit(origin)
        if parsed.scheme not in ('http', 'https') or not parsed.hostname or parsed.query or parsed.fragment or parsed.username or parsed.path:
            raise ValueError('Valid application origin required')
        if s.alipay_environment == 'production' and parsed.scheme != 'https':
            raise ValueError('Production requires HTTPS')
        notify = s.alipay_notify_url.strip()
        if notify:
            target = urlsplit(notify)
            if target.scheme not in ('http', 'https') or not target.hostname or target.username or target.fragment:
                raise ValueError('Valid optional notification URL required')
        return PaymentConfig(app_id, seller_id, s.alipay_environment, gateway,
                             origin + '/billing/return', notify, private, public)
    except PaymentUnavailable:
        raise
    except Exception:
        raise PaymentUnavailable('支付配置不完整，请联系管理员') from None


class AlipayGateway:
    def __init__(self, config=None):
        from alipay.aop.api.AlipayClientConfig import AlipayClientConfig
        from alipay.aop.api.DefaultAlipayClient import DefaultAlipayClient
        self.config = config or load_config()
        sdk = AlipayClientConfig()
        sdk.server_url = self.config.gateway
        sdk.app_id = self.config.app_id
        sdk.app_private_key = self.config.app_private_key
        sdk.alipay_public_key = self.config.alipay_public_key
        sdk.charset, sdk.sign_type, sdk.skip_sign, sdk.timeout = 'utf-8', 'RSA2', False, 10
        # The SDK otherwise logs complete signed requests and responses when a logger is supplied.
        try:
            self.client = DefaultAlipayClient(alipay_client_config=sdk, logger=None)
        except Exception:
            raise PaymentUnavailable('支付SDK配置需要管理员核对') from None

    def payment_form(self, order):
        from alipay.aop.api.request.AlipayTradePagePayRequest import AlipayTradePagePayRequest
        from alipay.aop.api.domain.AlipayTradePagePayModel import AlipayTradePagePayModel
        request, model = AlipayTradePagePayRequest(), AlipayTradePagePayModel()
        model.out_trade_no, model.subject = order.out_trade_no, order.title
        model.total_amount = f'{order.amount_cents // 100}.{order.amount_cents % 100:02d}'
        model.product_code = 'FAST_INSTANT_TRADE_PAY'
        model.timeout_express = '15m'
        request.biz_model = model
        request.return_url = self.config.return_url + '?order=' + order.id
        if self.config.notify_url:
            request.notify_url = self.config.notify_url
        try:
            form = self.client.page_execute(request, http_method='POST')
            if not isinstance(form, str) or '<form ' not in form:
                raise ValueError('No payment form')
            return form
        except Exception:
            raise ProviderUnavailable('暂时无法打开支付页面，请稍后重试') from None

    def _execute(self, request):
        try:
            # The installed SDK verifies the response signature and returns the INNER JSON object.
            # Missing signatures and invalid signatures raise; there is no unsigned fallback.
            response = self.client.execute(request)
            data = json.loads(response)
            if not isinstance(data, dict) or not isinstance(data.get('code'), str):
                raise ValueError('Unexpected response')
            return data
        except Exception:
            raise ProviderUnavailable('支付宝结果暂未确认，系统会继续查询') from None

    def query(self, order):
        from alipay.aop.api.request.AlipayTradeQueryRequest import AlipayTradeQueryRequest
        from alipay.aop.api.domain.AlipayTradeQueryModel import AlipayTradeQueryModel
        request, model = AlipayTradeQueryRequest(), AlipayTradeQueryModel()
        model.out_trade_no = order.out_trade_no
        request.biz_model = model
        return self._execute(request)

    def close(self, order):
        from alipay.aop.api.request.AlipayTradeCloseRequest import AlipayTradeCloseRequest
        from alipay.aop.api.domain.AlipayTradeCloseModel import AlipayTradeCloseModel
        request, model = AlipayTradeCloseRequest(), AlipayTradeCloseModel()
        model.out_trade_no = order.out_trade_no
        request.biz_model = model
        return self._execute(request)

    def refund(self, order, refund):
        from alipay.aop.api.request.AlipayTradeRefundRequest import AlipayTradeRefundRequest
        from alipay.aop.api.domain.AlipayTradeRefundModel import AlipayTradeRefundModel
        request, model = AlipayTradeRefundRequest(), AlipayTradeRefundModel()
        model.out_trade_no, model.out_request_no = order.out_trade_no, refund.id
        model.refund_amount = f'{refund.amount_cents // 100}.{refund.amount_cents % 100:02d}'
        model.refund_reason = '商户确认的订单退款'
        request.biz_model = model
        return self._execute(request)

    def refund_query(self, order, refund):
        from alipay.aop.api.request.AlipayTradeFastpayRefundQueryRequest import AlipayTradeFastpayRefundQueryRequest
        from alipay.aop.api.domain.AlipayTradeFastpayRefundQueryModel import AlipayTradeFastpayRefundQueryModel
        request, model = AlipayTradeFastpayRefundQueryRequest(), AlipayTradeFastpayRefundQueryModel()
        model.out_trade_no, model.out_request_no = order.out_trade_no, refund.id
        request.biz_model = model
        return self._execute(request)

    def verify_notification(self, params):
        from alipay.aop.api.util.SignatureUtils import get_sign_content, verify_with_rsa
        try:
            if params.get('app_id') != self.config.app_id or params.get('sign_type') != 'RSA2':
                return False
            # Preserve all original values; only signature metadata is excluded by the protocol.
            signed = {k: v for k, v in params.items() if k not in ('sign', 'sign_type') and v != ''}
            return verify_with_rsa(self.config.alipay_public_key,
                                   get_sign_content(signed).encode('utf-8'), params['sign'])
        except Exception:
            return False

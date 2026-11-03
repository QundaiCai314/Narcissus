"""Public HTTP fetcher: validate every DNS result, connect to the pinned IP, verify TLS host.

No ambient proxy, cookies, authentication, automatic redirects, or browser execution.
"""
import http.client
import ipaddress
import re
import socket
import ssl
import time
import json
from urllib.parse import urlsplit, urljoin, quote
from lxml import html
from .config import settings
from .source_parsing import decode_text, unit
from .pdf_processing import InvalidPDF


def validate_url(url):
    try:
        if len(url) > 2048 or re.search(r"[\x00-\x20\\]", url):
            raise ValueError()
        parsed = urlsplit(url)
        if parsed.scheme not in ("http", "https") or not parsed.hostname or parsed.username or parsed.password:
            raise ValueError()
        host = parsed.hostname.encode("idna").decode("ascii")
        if "%" in host or host.rstrip(".").lower() in ("localhost", "metadata.google.internal"):
            raise ValueError()
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        if port != (443 if parsed.scheme == "https" else 80):
            raise ValueError()
        return parsed, host, port
    except (ValueError, UnicodeError):
        raise InvalidPDF("仅支持公开 HTTP/HTTPS 网页及标准 80/443 端口，不允许登录凭证或本机地址") from None


def resolve_public(host, port):
    try:
        try:
            addresses = [str(ipaddress.ip_address(host))]
        except ValueError:
            if settings().web_dns_mode == "cloudflare":
                addresses = encrypted_dns(host)
            else:
                records = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
                addresses = list(dict.fromkeys(r[4][0] for r in records))
        if not addresses:
            raise ValueError()
        for address in addresses:
            ip = ipaddress.ip_address(address)
            if not ip.is_global or ip.is_multicast or ip.is_reserved or any(getattr(ip, attr, None) is not None for attr in ("ipv4_mapped", "sixtofour", "teredo")):
                raise ValueError()
        return addresses
    except (OSError, ValueError):
        raise InvalidPDF("网址无法解析为允许访问的公网地址；禁止本机、内网及云元数据地址") from None


def encrypted_dns(host):
    """Explicit deployment option for fake-IP VPNs; never a fallback for blocked addresses.

    Resolver IP, TLS identity, and API path are fixed, not user-controlled.
    Both A and AAAA responses still pass the complete public-address validation.
    """
    addresses = []
    for kind in (1, 28):
        conn = connect_pinned("cloudflare-dns.com", 443, "1.1.1.1", True, 5)
        try:
            conn.request("GET", f"/dns-query?name={quote(host,safe='')}&type={kind}", headers={"Accept": "application/dns-json", "Accept-Encoding": "identity"})
            response = conn.getresponse()
            raw = response.read(65537)
            if response.status != 200 or len(raw) > 65536:
                raise ValueError()
            data = json.loads(raw)
            if data.get("Status") != 0:
                raise ValueError()
            addresses.extend(a["data"] for a in data.get("Answer", []) if a.get("type") in (1, 28))
        finally:
            conn.close()
    return list(dict.fromkeys(addresses))


def connect_pinned(host, port, ip, secure, timeout):
    connection = http.client.HTTPConnection(host, port, timeout=timeout)
    # A numeric literal is used for the only socket connection, preventing a second DNS lookup.
    raw = socket.create_connection((ip, port), timeout=timeout)
    try:
        connection.sock = ssl.create_default_context().wrap_socket(raw, server_hostname=host) if secure else raw
    except BaseException:
        raw.close()
        raise
    return connection


def fetch_public(url):
    s = settings()
    started = time.monotonic()
    original = url
    for hop in range(min(s.web_max_redirects, 5)+1):
        parsed, host, port = validate_url(url)
        addresses = resolve_public(host, port)
        left = min(s.web_timeout_seconds, 40) - (time.monotonic()-started)
        if left <= 0:
            raise InvalidPDF("网页读取超时，可改为粘贴正文")
        conn = None
        try:
            conn = connect_pinned(host, port, addresses[0], parsed.scheme == "https", left)
            target = quote(parsed.path or "/", safe="/%:@!$&'()*+,;=-._~")
            if parsed.query:
                target += "?" + quote(parsed.query, safe="%=&?/:@!$'()*+,;~-._")
            conn.request("GET", target, headers={"User-Agent": "Narcissus-Import/5.0", "Accept": "text/html,text/plain", "Accept-Encoding": "identity"})
            response = conn.getresponse()
            if response.status in (301, 302, 303, 307, 308):
                location = response.getheader("Location")
                if not location or hop == min(s.web_max_redirects, 5):
                    raise InvalidPDF("网页跳转过多或地址无效，可粘贴正文")
                url = urljoin(url, location)
                continue
            if response.status != 200:
                raise InvalidPDF("网页不可直接读取，可能需要登录、付费或验证；请粘贴可合法使用的正文")
            mime = (response.getheader("Content-Type") or "").split(";")[0].lower()
            if mime not in ("text/html", "text/plain", "application/xhtml+xml"):
                raise InvalidPDF("链接不是普通网页正文，请直接上传文件")
            if response.getheader("Content-Encoding", "identity").lower() not in ("", "identity"):
                raise InvalidPDF("网页返回压缩内容，暂不支持，请粘贴正文")
            length = response.getheader("Content-Length")
            if length and (not length.isdigit() or int(length) > s.web_max_bytes):
                raise InvalidPDF("网页响应过大，请粘贴需要的正文")
            content = bytearray()
            while True:
                left = min(s.web_timeout_seconds, 40) - (time.monotonic()-started)
                if left <= 0:
                    raise InvalidPDF("网页读取超时，请粘贴正文")
                if conn.sock:
                    conn.sock.settimeout(left)
                block = response.read1(min(65536, s.web_max_bytes+1-len(content)))
                if not block:
                    break
                content.extend(block)
                if len(content) > s.web_max_bytes:
                    raise InvalidPDF("网页响应过大，请粘贴需要的正文")
            return bytes(content), {"url": url, "original_url": original, "domain": host, "mime": mime}
        except InvalidPDF:
            raise
        except TimeoutError:
            raise InvalidPDF("网页读取超时，请重试或粘贴正文") from None
        except (OSError, http.client.HTTPException):
            raise InvalidPDF("网页连接失败，请重试或粘贴正文") from None
        finally:
            if conn:
                conn.close()
    raise InvalidPDF("网页跳转超过上限")


def extract_web(data, meta):
    text, encoding = decode_text(data)
    if meta["mime"] == "text/plain":
        from .source_parsing import text_units
        if len(text.strip()) < 100:
            raise InvalidPDF("网页没有足够正文，请粘贴正文")
        return meta["domain"], text_units(text), {**meta, "encoding": encoding, "method": "web-text"}
    try:
        root = html.fromstring(text)
    except Exception:
        raise InvalidPDF("网页正文无法提取，请粘贴正文") from None
    title = " ".join(root.xpath("//title/text()"))[:240].strip() or meta["domain"]
    if root.xpath('//input[translate(@type,"PASSWORD","password")="password"]') or re.search(r"登录|登入|验证码|访问验证|安全验证|captcha|sign.?in|just a moment|access denied", title, re.I):
        raise InvalidPDF("页面需要登录或访问验证，请粘贴正文")
    for element in root.xpath("//script|//style|//noscript|//iframe|//nav|//footer|//header|//form|//aside|//svg"):
        element.drop_tree()
    containers = root.xpath("//article|//main|//*[@role='main']")
    container = max(containers, key=lambda e: len(e.text_content())) if containers else root
    elements = container.xpath(".//h1|.//h2|.//h3|.//h4|.//h5|.//h6|.//dt|.//p|.//li|.//tr|.//pre")
    units, heading = [], ""
    for element in elements:
        if element.tag in ("p", "li") and any(p.tag in ("li", "tr") for p in element.iterancestors() if p is not container):
            continue
        value = " ".join(element.text_content().split())
        if not value:
            continue
        if element.tag.startswith("h") or element.tag == "dt":
            heading = value
        units.append(unit(value, len(units)+1, f"第 {len(units)+1} 段", heading=heading,
                          paragraph=len(units)+1, kind="heading" if element.tag.startswith("h") or element.tag == "dt" else "paragraph"))
    body = "\n".join(u["text"] for u in units)
    if len(body) < 100 or re.search(r"登录后.{0,8}(阅读|查看)|订阅后.{0,8}(阅读|查看)|付费.{0,5}(解锁|阅读)|完成.{0,5}验证码|enable javascript to|verify you are human", body, re.I):
        raise InvalidPDF("未取得完整正文，页面可能需要登录、付费、验证或脚本；请粘贴正文")
    # Metadata is deliberately conservative; absent or conflicting bylines are not inferred.
    authors = list(dict.fromkeys(x.strip() for x in root.xpath('//meta[translate(@name,"AUTHOR","author")="author"]/@content') if x.strip()))
    dates = list(dict.fromkeys(root.xpath('//meta[@property="article:published_time"]/@content')))
    return title, units, {**meta, "method": "web-html", "encoding": encoding,
        "author": authors[0][:200] if len(authors) == 1 else None,
        "published_at": dates[0] if len(dates) == 1 and re.fullmatch(r"\d{4}-\d{2}-\d{2}[T ][0-9:+.Z-]+", dates[0]) else None,
        "warnings": ["已提取正文快照，请核对完整性；原网页此后可能变化"]}

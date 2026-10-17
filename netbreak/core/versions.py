from __future__ import annotations

import asyncio
import re
import ssl

from ..ports import service_for

HTTP_PORTS = {
    80, 81, 88, 591, 2082, 2086, 3000, 4000, 5000, 5985, 7001, 8000, 8008,
    8010, 8042, 8080, 8081, 8086, 8088, 8090, 8161, 8180, 8200, 8300, 8500,
    8600, 8888, 8983, 9000, 9060, 9080, 9090, 9091, 9200, 9600, 9999,
    10000, 15672, 50070,
}
TLS_PORTS = {443, 465, 636, 993, 995, 3389, 4443, 5986, 6443, 8443, 9443, 10250}
TLS_HTTP_PORTS = {443, 4443, 5986, 6443, 8443, 9443, 10250}

BANNER_PORTS = {21, 22, 23, 25, 110, 143, 587, 873, 5900, 6667}
NON_HTTP_PORTS = {3306, 6379, 11211, 27017, 5432, 1433, 5060, 5061, 5672, 1883, 5353}

_RE_SSH = re.compile(r"SSH-(\d+\.\d+)-(\S+)")
_RE_HTTP_SERVER = re.compile(r"^server:\s*(.+?)\s*$", re.I | re.M)
_RE_HTTP_POWERED = re.compile(r"^x-powered-by:\s*(.+?)\s*$", re.I | re.M)
_RE_HTTP_TITLE = re.compile(rb"<title[^>]*>(.{0,120}?)</title>", re.I | re.S)
_RE_VERSION = re.compile(r"(\d+[\w.\-]*)")
_RE_FTP = re.compile(r"^220[- ].*?\(([^)]+)\)|^220[- ]+(.+)$", re.M)
_RE_REDIS = re.compile(r"redis_version:([\w.\-]+)")
_RE_MEMCACHED = re.compile(r"VERSION\s+([\w.\-]+)", re.I)
_RE_MYSQL = re.compile(rb"([\d]+\.[\d]+\.[\d]+[\w.\-]*)")
_RE_RFB = re.compile(r"RFB\s+([\d.]+)")
_RE_SMTP = re.compile(r"^220[- ].*?(ESMTP\s+)?(.+)$", re.M)
_RE_POP3 = re.compile(r"^\+OK\s+(.*)$", re.M)
_RE_IMAP = re.compile(r"^\*\s+OK\s+(.*)$", re.M)

PRODUCT_HINTS = {
    "openssh": "OpenSSH", "dropbear": "Dropbear SSH", "vsftpd": "vsftpd",
    "proftpd": "ProFTPD", "pure-ftpd": "Pure-FTPd", "filezilla": "FileZilla Server",
    "microsoft ftp": "Microsoft FTP", "postfix": "Postfix", "exim": "Exim",
    "sendmail": "Sendmail", "dovecot": "Dovecot", "courier": "Courier",
    "nginx": "nginx", "apache": "Apache httpd", "iis": "Microsoft IIS",
    "microsoft-iis": "Microsoft IIS", "caddy": "Caddy", "lighttpd": "lighttpd",
    "tomcat": "Apache Tomcat", "jetty": "Jetty", "gunicorn": "gunicorn",
    "werkzeug": "Werkzeug", "redis": "Redis", "memcached": "memcached",
    "mysql": "MySQL", "mariadb": "MariaDB", "postgres": "PostgreSQL",
    "elasticsearch": "Elasticsearch", "kibana": "Kibana", "rabbitmq": "RabbitMQ",
    "kubernetes": "Kubernetes", "minio": "MinIO", "consul": "Consul",
    "jenkins": "Jenkins", "grafana": "Grafana", "prometheus": "Prometheus",
    "docker": "Docker", "openssl": "OpenSSL",
}


class Detection:
    def __init__(self, service: str | None = None) -> None:
        self.service = service
        self.product: str | None = None
        self.version: str | None = None
        self.banner: str | None = None
        self.info: dict[str, str] = {}

    def hint_product(self, text: str) -> None:
        low = text.lower()
        for key, name in PRODUCT_HINTS.items():
            if key in low:
                self.product = self.product or name
                match = _RE_VERSION.search(text)
                if match and not self.version:
                    self.version = match.group(1)
                return


def _decode(data: bytes) -> str:
    return data.decode("utf-8", "replace").strip("\x00\r\n\t ")


async def _read(reader: asyncio.StreamReader, timeout: float, limit: int = 16384) -> bytes:
    try:
        return await asyncio.wait_for(reader.read(limit), timeout)
    except (asyncio.TimeoutError, OSError, ssl.SSLError):
        return b""


async def _connect(host: str, port: int, timeout: float, tls: bool = False):
    if tls:
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE
        context.set_ciphers("DEFAULT@SECLEVEL=1")
        return await asyncio.wait_for(
            asyncio.open_connection(host, port, ssl=context, server_hostname=None), timeout
        )
    return await asyncio.wait_for(asyncio.open_connection(host, port), timeout)


def _parse_http(detection: Detection, body: bytes, host: str) -> None:
    text = _decode(body)
    if detection.banner is None:
        detection.banner = text[:400]
    server = _RE_HTTP_SERVER.search(text)
    if server:
        value = server.group(1)
        detection.product = detection.product or value
        match = _RE_VERSION.search(value)
        if match:
            detection.version = detection.version or match.group(1)
        detection.hint_product(value)
    powered = _RE_HTTP_POWERED.search(text)
    if powered:
        detection.info["x-powered-by"] = powered.group(1)
    title = _RE_HTTP_TITLE.search(body)
    if title:
        detection.info["title"] = _decode(title.group(1))[:80]
    first = text.splitlines()[0] if text else ""
    if first.startswith("HTTP/"):
        detection.info["status"] = first.split(" ", 2)[-1][:60]
    if detection.service is None:
        detection.service = "http"


def _parse_ssh(detection: Detection, banner: str) -> None:
    match = _RE_SSH.search(banner)
    if match:
        detection.service = "ssh"
        detection.info["protocol"] = match.group(1)
        software = match.group(2)
        detection.product = "OpenSSH" if software.lower().startswith("openssh") else software.split("_")[0]
        version = _RE_VERSION.search(software)
        if version:
            detection.version = version.group(1)
        for distro in ("ubuntu", "debian", "freebsd", "raspbian", "centos", "alpine"):
            if distro in software.lower():
                detection.info["platform"] = distro.capitalize()
                break


async def detect(host: str, port: int, timeout: float = 3.0) -> Detection:
    detection = Detection(service_for(port))
    reader = None
    writer = None
    try:
        if port in TLS_PORTS:
            try:
                reader, writer = await _connect(host, port, timeout, tls=True)
            except (OSError, asyncio.TimeoutError, ssl.SSLError):
                return detection
            tls_object = writer.get_extra_info("ssl_object")
            if tls_object is not None:
                detection.info["tls"] = f"{tls_object.version()} {tls_object.cipher()[0]}"
                detection.service = detection.service or "ssl"
            if port not in TLS_HTTP_PORTS:
                if detection.service in (None, "ssl"):
                    detection.service = detection.service or service_for(port)
                return detection
        else:
            reader, writer = await _connect(host, port, timeout)
            banner = await _read(reader, min(0.6, timeout), 2048)
            if banner:
                detection.banner = _decode(banner)[:400]

        text = detection.banner or ""

        if port in HTTP_PORTS or port in TLS_HTTP_PORTS or text.startswith("HTTP/"):
            request = (
                f"GET / HTTP/1.0\r\nHost: {host}\r\n"
                "User-Agent: NetBreak/2.0\r\nAccept: */*\r\n\r\n"
            )
            writer.write(request.encode())
            await writer.drain()
            body = await _read(reader, timeout)
            _parse_http(detection, body, host)
        elif text.startswith("SSH-"):
            _parse_ssh(detection, text)
        elif port == 6379:
            writer.write(b"INFO server\r\n")
            await writer.drain()
            body = _decode(await _read(reader, timeout))
            match = _RE_REDIS.search(body)
            detection.service = "redis"
            detection.product = "Redis"
            if match:
                detection.version = match.group(1)
        elif port == 11211:
            writer.write(b"version\r\n")
            await writer.drain()
            body = _decode(await _read(reader, timeout))
            match = _RE_MEMCACHED.search(body)
            detection.service = "memcached"
            detection.product = "memcached"
            if match:
                detection.version = match.group(1)
        elif port == 3306:
            raw = await _read(reader, timeout, 512)
            match = _RE_MYSQL.search(raw or b"")
            detection.service = "mysql"
            detection.product = "MySQL"
            if match:
                detection.version = match.group(1).decode()
        elif port == 5900 or text.startswith("RFB"):
            match = _RE_RFB.search(text)
            detection.service = "vnc"
            detection.product = "VNC"
            if match:
                detection.version = match.group(1)
        elif port == 3389:
            detection.service = "ms-wbt-server"
            detection.product = "Microsoft Terminal Services"
        elif not text and port not in BANNER_PORTS and port not in NON_HTTP_PORTS:
            request = (
                f"GET / HTTP/1.0\r\nHost: {host}\r\n"
                "User-Agent: NetBreak/2.0\r\nAccept: */*\r\n\r\n"
            )
            writer.write(request.encode())
            await writer.drain()
            body = await _read(reader, timeout)
            if body:
                if body.startswith(b"HTTP/"):
                    _parse_http(detection, body, host)
                elif body[:3] == b"\x16\x03\x01":
                    detection.info["tls"] = "tls-handshake"
                    detection.service = detection.service or "ssl"
                else:
                    detection.banner = _decode(body)[:200]
                    detection.hint_product(detection.banner)
        elif text:
            head = text.splitlines()[0]
            detection.hint_product(text)
            if port == 21:
                detection.service = "ftp"
                match = _RE_FTP.search(text)
                if match:
                    detection.product = detection.product or (match.group(1) or match.group(2) or "").strip()[:40]
            elif port in (25, 587):
                detection.service = "smtp"
                match = _RE_SMTP.search(text)
                if match:
                    detection.info["banner"] = (match.group(2) or "")[:60]
                detection.hint_product(text)
            elif port == 110:
                detection.service = "pop3"
                match = _RE_POP3.search(text)
                if match:
                    detection.info["banner"] = match.group(1)[:60]
            elif port == 143:
                detection.service = "imap"
                match = _RE_IMAP.search(text)
                if match:
                    detection.info["banner"] = match.group(1)[:60]
            detection.banner = detection.banner or head[:200]
    except (OSError, asyncio.TimeoutError, ssl.SSLError):
        pass
    finally:
        if writer is not None:
            try:
                writer.close()
                await writer.wait_closed()
            except (OSError, ssl.SSLError):
                pass
    return detection


def apply(detection: Detection, result) -> None:
    if detection.service:
        result.service = detection.service
    if detection.product:
        result.product = detection.product
    if detection.version:
        result.version = detection.version
    if detection.banner:
        result.banner = detection.banner
    for key, value in detection.info.items():
        result.info[key] = value

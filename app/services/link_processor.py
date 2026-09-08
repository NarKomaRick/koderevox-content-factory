import asyncio
import ipaddress
import socket
from collections.abc import Awaitable, Callable
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup

from app.schemas.processing import LinkContent
from app.services.errors import PermanentProcessingError, TemporaryProcessingError

IPAddress = ipaddress.IPv4Address | ipaddress.IPv6Address
Resolver = Callable[[str, int], Awaitable[list[IPAddress]]]


async def public_dns_resolver(host: str, port: int) -> list[IPAddress]:
    loop = asyncio.get_running_loop()
    try:
        records = await loop.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise PermanentProcessingError("Hostname cannot be resolved") from exc
    return list({ipaddress.ip_address(record[4][0]) for record in records})


def ensure_public_ip(address: IPAddress) -> None:
    if not address.is_global:
        raise PermanentProcessingError("URL resolves to a non-public network")


class LinkProcessor:
    def __init__(
        self,
        *,
        timeout_seconds: float = 15,
        max_size_bytes: int = 10 * 1024 * 1024,
        max_redirects: int = 5,
        resolver: Resolver = public_dns_resolver,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.max_size_bytes = max_size_bytes
        self.max_redirects = max_redirects
        self.resolver = resolver
        self._owns_client = client is None
        self.client = client or httpx.AsyncClient(
            timeout=timeout_seconds,
            follow_redirects=False,
            trust_env=False,
            headers={"User-Agent": "KoderevoxContentFactory/0.2"},
        )

    async def aclose(self) -> None:
        if self._owns_client:
            await self.client.aclose()

    async def process(self, url: str) -> LinkContent:
        requested_url = url
        current_url = url
        for redirect_count in range(self.max_redirects + 1):
            await self._validate_url(current_url)
            try:
                async with self.client.stream(
                    "GET", current_url, follow_redirects=False
                ) as response:
                    if response.status_code in {301, 302, 303, 307, 308}:
                        location = response.headers.get("location")
                        if not location:
                            raise PermanentProcessingError("Redirect has no Location header")
                        if redirect_count >= self.max_redirects:
                            raise PermanentProcessingError("Too many redirects")
                        current_url = urljoin(current_url, location)
                        continue
                    if response.status_code >= 500:
                        raise TemporaryProcessingError(
                            f"Remote server returned {response.status_code}"
                        )
                    if response.status_code >= 400:
                        raise PermanentProcessingError(
                            f"Remote server returned {response.status_code}"
                        )
                    content_type = response.headers.get("content-type", "").split(";", 1)[0]
                    if content_type not in {"text/html", "application/xhtml+xml"}:
                        raise PermanentProcessingError("URL is not an HTML page")
                    declared_size = int(response.headers.get("content-length", "0") or 0)
                    if declared_size > self.max_size_bytes:
                        raise PermanentProcessingError("URL response exceeds size limit")
                    body = bytearray()
                    async for chunk in response.aiter_bytes():
                        body.extend(chunk)
                        if len(body) > self.max_size_bytes:
                            raise PermanentProcessingError("URL response exceeds size limit")
                    return self._extract(requested_url, current_url, content_type, bytes(body))
            except httpx.TimeoutException as exc:
                raise TemporaryProcessingError("URL fetch timed out") from exc
            except httpx.TransportError as exc:
                raise TemporaryProcessingError("URL fetch failed") from exc
        raise PermanentProcessingError("Too many redirects")

    async def _validate_url(self, url: str) -> None:
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise PermanentProcessingError("Only absolute HTTP/HTTPS URLs are allowed")
        if parsed.username or parsed.password:
            raise PermanentProcessingError("Credentials in URLs are not allowed")
        hostname = parsed.hostname.rstrip(".").lower()
        if hostname == "localhost" or hostname.endswith(".localhost"):
            raise PermanentProcessingError("Localhost URLs are not allowed")
        try:
            literal_address = ipaddress.ip_address(hostname)
        except ValueError:
            literal_address = None
        if literal_address is not None:
            ensure_public_ip(literal_address)
        else:
            try:
                port = parsed.port or (443 if parsed.scheme == "https" else 80)
            except ValueError as exc:
                raise PermanentProcessingError("URL contains an invalid port") from exc
            addresses = await self.resolver(hostname, port)
            if not addresses:
                raise PermanentProcessingError("Hostname has no addresses")
            for address in addresses:
                ensure_public_ip(address)

    def _extract(
        self, requested_url: str, final_url: str, content_type: str, body: bytes
    ) -> LinkContent:
        soup = BeautifulSoup(body, "html.parser")
        for element in soup(["script", "style", "noscript", "nav", "footer", "header", "aside"]):
            element.decompose()
        title = self._meta(soup, "og:title") or (
            soup.title.get_text(strip=True) if soup.title else None
        )
        description = self._meta(soup, "og:description") or self._named_meta(soup, "description")
        site_name = self._meta(soup, "og:site_name")
        main = soup.find("main") or soup.find("article") or soup.body or soup
        text = "\n".join(line.strip() for line in main.get_text("\n").splitlines() if line.strip())
        if not text:
            raise PermanentProcessingError("HTML page contains no extractable text")
        return LinkContent(
            requested_url=requested_url,
            final_url=final_url,
            title=title,
            description=description,
            site_name=site_name,
            main_text=text,
            content_type=content_type,
        )

    @staticmethod
    def _meta(soup: BeautifulSoup, property_name: str) -> str | None:
        tag = soup.find("meta", attrs={"property": property_name})
        value = tag.get("content") if tag else None
        return str(value).strip() if value else None

    @staticmethod
    def _named_meta(soup: BeautifulSoup, name: str) -> str | None:
        tag = soup.find("meta", attrs={"name": name})
        value = tag.get("content") if tag else None
        return str(value).strip() if value else None

"""SSRF-safe downloader primitives for future explicit web-asset providers."""

import ipaddress
import socket
from urllib.parse import urlparse

from app.director.policies import DirectorToolError


class SafeURLValidator:
    def __init__(self, *, max_redirects: int = 5) -> None:
        self.max_redirects = max_redirects

    def validate(self, url: str) -> str:
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise DirectorToolError("UNSAFE_URL", "Only http(s) URLs with a hostname are allowed")
        hostname = parsed.hostname.casefold().rstrip(".")
        if hostname in {"localhost", "localhost.localdomain"}:
            raise DirectorToolError("UNSAFE_URL", "Localhost URLs are not allowed")
        try:
            addresses = [ipaddress.ip_address(hostname)]
        except ValueError:
            try:
                addresses = [
                    ipaddress.ip_address(info[4][0]) for info in socket.getaddrinfo(hostname, None)
                ]
            except OSError as exc:
                raise DirectorToolError("UNSAFE_URL", "Hostname cannot be resolved") from exc
        if any(
            address.is_private
            or address.is_loopback
            or address.is_link_local
            or address.is_reserved
            for address in addresses
        ):
            raise DirectorToolError("UNSAFE_URL", "Private and metadata networks are not allowed")
        return parsed.geturl()

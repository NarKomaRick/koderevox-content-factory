import ipaddress

import httpx
import pytest

from app.services.errors import PermanentProcessingError
from app.services.link_processor import LinkProcessor


async def public_resolver(_host: str, _port: int):
    return [ipaddress.ip_address("93.184.216.34")]


async def private_resolver(_host: str, _port: int):
    return [ipaddress.ip_address("10.20.30.40")]


async def test_valid_public_url_extracts_main_content() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"content-type": "text/html"},
            text=(
                "<html><head><title>Useful article</title>"
                '<meta property="og:site_name" content="Example"></head>'
                "<body><nav>Menu</nav><main><h1>Heading</h1><p>Main text.</p></main></body></html>"
            ),
            request=request,
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    processor = LinkProcessor(resolver=public_resolver, client=client)

    result = await processor.process("https://example.com/article")

    assert result.title == "Useful article"
    assert result.site_name == "Example"
    assert "Main text" in result.main_text
    assert "Menu" not in result.main_text
    await client.aclose()


@pytest.mark.parametrize(
    "url",
    [
        "notaurl",
        "ftp://example.com/file",
        "http://localhost/admin",
        "http://127.0.0.1/private",
        "http://10.0.0.1/",
        "http://172.16.1.1/",
        "http://192.168.1.1/",
        "http://[::1]/",
        "http://[fc00::1]/",
        "http://169.254.169.254/latest/meta-data/",
    ],
)
async def test_invalid_or_private_urls_are_blocked(url: str) -> None:
    processor = LinkProcessor(resolver=public_resolver)
    with pytest.raises(PermanentProcessingError):
        await processor.process(url)


async def test_hostname_resolving_to_private_ip_is_blocked() -> None:
    processor = LinkProcessor(resolver=private_resolver)
    with pytest.raises(PermanentProcessingError):
        await processor.process("http://postgres/internal")


async def test_redirect_to_private_address_is_blocked() -> None:
    calls = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(302, headers={"location": "http://127.0.0.1/admin"}, request=request)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    processor = LinkProcessor(resolver=public_resolver, client=client)

    with pytest.raises(PermanentProcessingError):
        await processor.process("https://example.com/start")

    assert calls == 1
    await client.aclose()

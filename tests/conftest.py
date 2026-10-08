import functools
import http.server
import threading
from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures" / "spa"


@pytest.fixture(scope="session")
def spa_url():
    """Serve a SPA de exemplo (iframes aninhados, renderização progressiva, shadow DOM) numa porta livre."""
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(FIXTURES))
    handler.log_message = lambda *args: None  # type: ignore[attr-defined]
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_address[1]}/index.html"
    server.shutdown()

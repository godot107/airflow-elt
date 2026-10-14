"""The webhook gets a Slack-style JSON payload; no URL means log only; a broken webhook never raises."""
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

from taxi import alerts


def test_no_url_logs_only(monkeypatch):
    monkeypatch.delenv("ALERT_WEBHOOK_URL", raising=False)
    assert alerts.notify("hello") is False


def test_posts_text_to_the_webhook(monkeypatch):
    received = []

    class Hook(BaseHTTPRequestHandler):
        def do_POST(self):
            received.append(json.loads(self.rfile.read(int(self.headers["Content-Length"]))))
            self.send_response(200)
            self.end_headers()

        def log_message(self, *args):
            pass

    server = HTTPServer(("127.0.0.1", 0), Hook)
    threading.Thread(target=server.handle_request, daemon=True).start()
    monkeypatch.setenv("ALERT_WEBHOOK_URL", f"http://127.0.0.1:{server.server_port}/hook")
    assert alerts.notify(":warning: gate warning") is True
    assert received == [{"text": ":warning: gate warning"}]
    server.server_close()


def test_unreachable_webhook_does_not_raise(monkeypatch):
    monkeypatch.setenv("ALERT_WEBHOOK_URL", "http://127.0.0.1:9/nothing-listens-here")
    assert alerts.notify("still fine") is False

#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
"""Serwer strony zakupowej: renderuje template z danymi i dodaje wybory do koszyka.

GET  /          -> assets/template.html z wstrzykniętym data.json (placeholder __DATA__)
POST /api/cart  -> {"items": [{"shop": "rossmann", "id": 123, "qty": 2}]}
                   dispatch po `shop`; zwraca {"results": [{"shop", "id", "ok", "message"}]}

Dodawanie do koszyka idzie przez CLI sklepu (subprocess), więc nowy sklep w przyszłości
to tylko nowy wpis w _SHOP_COMMANDS — bez zależności od kodu tego repo.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

_SKILL_DIR = Path(__file__).resolve().parent.parent
_DEFAULT_TEMPLATE = _SKILL_DIR / "assets" / "template.html"

# shop -> szablon komendy dodania do koszyka; uruchamiana w --repo (cwd)
_SHOP_COMMANDS = {
    "rossmann": ["uv", "run", "rossmann", "basket", "add", "{id}", "--qty", "{qty}"],
    "allegro": ["uv", "run", "allegro", "basket", "add", "{id}", "--qty", "{qty}"],
}


def _add_to_cart(shop: str, product_id: int, qty: int, repo: Path) -> tuple[bool, str]:
    command = _SHOP_COMMANDS.get(shop)
    if command is None:
        return False, f"nieobsługiwany sklep: {shop}"
    argv = [a.format(id=product_id, qty=qty) for a in command]
    proc = subprocess.run(argv, cwd=repo, capture_output=True, text=True, timeout=120)
    output = (proc.stdout if proc.returncode == 0 else proc.stderr).strip()
    return proc.returncode == 0, output or f"kod wyjścia {proc.returncode}"


class Handler(BaseHTTPRequestHandler):
    data: dict
    template: Path
    repo: Path

    def do_GET(self) -> None:  # noqa: N802 (API http.server)
        if self.path not in ("/", "/index.html"):
            self.send_error(404)
            return
        payload = json.dumps(self.data, ensure_ascii=False).replace("</", "<\\/")
        html = self.template.read_text(encoding="utf-8").replace("/*__DATA__*/null", payload)
        body = html.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self) -> None:  # noqa: N802
        if self.path != "/api/cart":
            self.send_error(404)
            return
        length = int(self.headers.get("Content-Length") or 0)
        try:
            items = json.loads(self.rfile.read(length)).get("items") or []
        except json.JSONDecodeError:
            self.send_error(400, "niepoprawny JSON")
            return
        results = []
        for item in items:
            try:
                ok, message = _add_to_cart(
                    item.get("shop", ""), int(item["id"]), int(item.get("qty") or 1), self.repo
                )
            except Exception as e:  # subprocess.TimeoutExpired, KeyError itd.
                ok, message = False, str(e)
            results.append({"shop": item.get("shop"), "id": item.get("id"), "ok": ok, "message": message})
        body = json.dumps({"results": results}, ensure_ascii=False).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt: str, *args) -> None:
        print(f"{self.address_string()} {fmt % args}", file=sys.stderr)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", required=True, type=Path, help="ścieżka do data.json")
    parser.add_argument("--template", type=Path, default=_DEFAULT_TEMPLATE)
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--repo", type=Path, default=Path.cwd(),
                        help="korzeń repo z CLI sklepów (cwd dla komend koszyka)")
    args = parser.parse_args()

    Handler.data = json.loads(args.data.read_text(encoding="utf-8"))
    Handler.template = args.template
    Handler.repo = args.repo.resolve()

    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    print(f"http://localhost:{args.port} (dane: {args.data}, koszyk przez CLI w {Handler.repo})")
    server.serve_forever()


if __name__ == "__main__":
    main()

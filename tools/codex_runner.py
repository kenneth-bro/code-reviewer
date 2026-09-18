from __future__ import annotations

import json
import os
import subprocess
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


def configured_workdir() -> Path:
    value = os.getenv("CODEX_RUNNER_WORKDIR", "").strip()
    if not value:
        raise RuntimeError("CODEX_RUNNER_WORKDIR is not configured")
    path = Path(value).expanduser().resolve()
    if not path.is_dir():
        raise RuntimeError(f"Codex Runner workdir does not exist: {path}")
    return path


def prompt(messages: list[dict[str, str]]) -> str:
    sections = []
    for message in messages:
        role = message.get("role", "user").upper()
        sections.append(f"[{role}]\n{message.get('content', '')}")
    sections.append("[RUNNER]\n仅执行代码审查，不修改工作目录内容；只返回审查结果。")
    return "\n\n".join(sections)


def command(workdir: Path, model: str | None) -> list[str]:
    result = [
        os.getenv("CODEX_RUNNER_BIN", "codex"),
        "exec",
        "--cd",
        str(workdir),
        "--sandbox",
        "read-only",
        "--ephemeral",
        "--skip-git-repo-check",
    ]
    selected_model = model or os.getenv("CODEX_RUNNER_MODEL", "").strip()
    if selected_model:
        result.extend(["--model", selected_model])
    result.append("-")
    return result


class RunnerHandler(BaseHTTPRequestHandler):
    def _write_json(self, status: int, payload: dict[str, str]) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        if self.path == "/health":
            self._write_json(HTTPStatus.OK, {"status": "ok"})
            return
        self._write_json(HTTPStatus.NOT_FOUND, {"detail": "Not found"})

    def do_POST(self) -> None:
        if self.path != "/review":
            self._write_json(HTTPStatus.NOT_FOUND, {"detail": "Not found"})
            return
        expected_token = os.getenv("CODEX_RUNNER_TOKEN", "")
        if expected_token and self.headers.get("Authorization") != f"Bearer {expected_token}":
            self._write_json(HTTPStatus.UNAUTHORIZED, {"detail": "Invalid Codex Runner token"})
            return

        try:
            length = int(self.headers.get("Content-Length", "0"))
            request = json.loads(self.rfile.read(length).decode("utf-8"))
            messages = request.get("messages") or []
            workdir = configured_workdir()
            timeout = float(os.getenv("CODEX_RUNNER_TIMEOUT_SECONDS", "900"))
            runner_env = os.environ.copy()
            codex_home = os.getenv("CODEX_RUNNER_CODEX_HOME", "").strip()
            if codex_home:
                runner_env["CODEX_HOME"] = str(Path(codex_home).expanduser().resolve())
            result = subprocess.run(
                command(workdir, request.get("model")),
                cwd=workdir,
                input=prompt(messages),
                text=True,
                capture_output=True,
                timeout=timeout,
                check=False,
                env=runner_env,
            )
            if result.returncode != 0:
                detail = result.stderr.strip() or result.stdout.strip() or "codex exec failed"
                self._write_json(HTTPStatus.BAD_GATEWAY, {"detail": detail[-2000:]})
                return
            content = result.stdout.strip()
            if not content:
                self._write_json(HTTPStatus.BAD_GATEWAY, {"detail": "codex exec returned empty output"})
                return
            self._write_json(HTTPStatus.OK, {"content": content})
        except subprocess.TimeoutExpired:
            self._write_json(HTTPStatus.GATEWAY_TIMEOUT, {"detail": "Codex Runner timed out"})
        except (OSError, RuntimeError, ValueError, TypeError, json.JSONDecodeError) as exc:
            self._write_json(HTTPStatus.SERVICE_UNAVAILABLE, {"detail": str(exc)})

    def log_message(self, format: str, *args: object) -> None:
        return


def main() -> None:
    host = os.getenv("CODEX_RUNNER_HOST", "0.0.0.0")
    port = int(os.getenv("CODEX_RUNNER_PORT", "8790"))
    server = ThreadingHTTPServer((host, port), RunnerHandler)
    print(f"Codex Runner listening on {host}:{port}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()

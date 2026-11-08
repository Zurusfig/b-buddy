"""Local coach server for the finance app. Start it with `python dev.py serve`.

    GET  /health   -> {"ok": true, "ready": bool, "reason": "..."}     (no secret needed)
    POST /ask      {"userId": 7, "question": "..."}  + header X-Coach-Secret
                   -> {"answer", "route", "answeredBy", "flags", "latencyS", "tip", "receipt": [...]}

The app's backend calls it after it has checked the user's login, and passes the user id from the
login token. The browser never talks to this server, the model never chooses the user, and the server
listens on 127.0.0.1 only. A shared secret stops other programs on the machine from asking as someone else.

Questions are answered one at a time (a single local model), and a question is refused up front when the
local model is not running, so nothing is silently sent to the gateway instead.
"""
from __future__ import annotations

import hmac
import json
import os
import re
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Callable

import requests

import agent
import db_data
from envfile import load_env
import persona_agent

HERE = Path(__file__).resolve().parent
HOST = "127.0.0.1"
MAX_BODY_BYTES = 4096
MAX_QUESTION_CHARS = 500
MAX_RESULT_CHARS = 1500
HIDDEN_CALLS = {"think_harder", "decline"}
_ask_lock = threading.Lock()
# One question runs at a time (the local model serves one request at a time anyway). A few more may wait their
# turn; beyond that the app is told "busy" at once instead of hanging until its own timeout (P9).
QUEUE_MAX = 3
QUEUE_WAIT_S = 150
_queue_lock = threading.Lock()
_waiting = 0
_warm = threading.Event()
_status: dict = {"ready": False, "reason": "starting"}
_refresher_running = False


def _git_commit() -> str | None:
    try:
        return subprocess.check_output(
            ["git", "-C", str(HERE.parents[1]), "rev-parse", "HEAD"],
            stderr=subprocess.DEVNULL, timeout=2, text=True).strip()
    except (OSError, subprocess.SubprocessError):
        return None


GIT_COMMIT = _git_commit()
CONFIG_NAME = f"app-routed-2026-10__{agent.SMALL_MODEL}__{agent.BIG_MODEL}"


def ollama_ready(model: str | None = None, url: str | None = None, timeout: float = 2.0) -> tuple[bool, str]:
    """(ready, reason): the local Ollama server answers and has the small model pulled."""
    model = model or agent.SMALL_MODEL
    try:
        r = requests.get((url or agent.OLLAMA_URL) + "/api/tags", timeout=timeout)
        r.raise_for_status()
        names = [m["name"] for m in r.json().get("models", [])]
    except Exception:
        return False, "ollama_offline"
    if not any(n == model or n.startswith(model) for n in names):
        return False, "model_missing"
    return True, ""


def warm_up() -> None:
    """Load the small model into memory so the first question does not pay the load time."""
    try:
        requests.post(agent.OLLAMA_URL + "/api/generate", timeout=300,
                      json={"model": agent.SMALL_MODEL, "prompt": "", "keep_alive": "10m"})
        _warm.set()
    except Exception:
        pass


def _refresh_status_forever(every_s: float = 3.0) -> None:
    """Keep the Ollama status fresh in the background so /health answers instantly, even while the model loads."""
    while True:
        ready, reason = ollama_ready()
        _status.update(ready=ready, reason=reason)
        time.sleep(every_s)


def health() -> dict:
    if _refresher_running:
        ready, reason = _status["ready"], _status["reason"]
    else:
        ready, reason = ollama_ready()
    if ready and not os.environ.get("COACH_DATABASE_URL"):
        ready, reason = False, "database_not_configured"
    return {"ok": True, "ready": ready, "reason": reason, "warm": _warm.is_set(), "queued": _waiting}


def _trim(value):
    text = json.dumps(value, ensure_ascii=False, default=str)
    if len(text) <= MAX_RESULT_CHARS:
        return value
    if isinstance(value, list):
        return {"shown": value[:10], "total": len(value)}
    return text[:MAX_RESULT_CHARS]


def shape(r: dict) -> dict:
    """The reply the app shows: answer text, who answered, and a receipt of what the code computed."""
    receipt = [{"tool": c["name"], "args": c.get("args") or {}, "result": _trim(c.get("result"))}
               for c in r["calls"] if c["name"] not in HIDDEN_CALLS and "result" in c
                and not (isinstance(c["result"], dict) and "error" in c["result"])]  # a failed lookup is not a figure
    tip = r.get("source") or next((c["result"] for c in r["calls"]
                                   if c["name"] == "lookup_guideline" and isinstance(c.get("result"), dict)), None)
    model = r.get("model")
    return {"answer": r["answer"], "route": r["route"], "intent": r.get("intent"),
            # "none" also covers replies code wrote itself (a breakdown, a no-data note): the model only chose the tool
            "answeredBy": "none" if model is None or {"code_reply", "known_gap"} & set(r["flags"])
                          else ("local" if agent.is_local(model) else "server"),
            "flags": r["flags"], "escalatedBy": r.get("escalated_by", []),
            "latencyS": round(r["latency"], 2),
            "options": r.get("options") or [],
            "tip": {k: tip.get(k) for k in ("id", "title", "source", "url", "read_more", "read_more_title")} if tip else None,
            "receipt": receipt}


def ask(user_id: int, question: str, data_factory: Callable = db_data.DbData,
        answerer: Callable = persona_agent.answer_for, uat: dict | None = None,
        persona: str | None = None) -> tuple[int, dict]:
    """(http status, body). Never raises: every failure is a short code the app can show in plain words."""
    meta = {"round": uat["round"] if uat else None,
            "tester_number": uat["tester_number"] if uat else None,
            "task_id": uat["task_id"] if uat else None,
            "chat_id": uat["chat_id"] if uat else None,
            "attempt": uat["attempt"] if uat else None,
            "git_commit": GIT_COMMIT, "config_name": CONFIG_NAME,
            "persona": persona}
    ready, reason = ollama_ready()
    if not ready:
        agent.LOG.write("coach_http", user_id=user_id, question=question, status=503, error=reason, **meta)
        return 503, {"error": reason}
    try:
        data = data_factory(user_id)
    except ValueError:
        agent.LOG.write("coach_http", user_id=user_id, question=question, status=404, error="no_data", **meta)
        return 404, {"error": "no_data"}
    except Exception as e:
        print(f"[coach] database error: {type(e).__name__}: {e}", file=sys.stderr)
        agent.LOG.write("coach_http", user_id=user_id, question=question, status=503, error="database_unavailable", **meta)
        return 503, {"error": "database_unavailable"}
    global _waiting
    with _queue_lock:
        if _waiting >= QUEUE_MAX:
            agent.LOG.write("coach_http", user_id=user_id, question=question, status=429, error="busy", waiting=_waiting, **meta)
            return 429, {"error": "busy"}
        _waiting += 1
    t0 = time.perf_counter()
    got = _ask_lock.acquire(timeout=QUEUE_WAIT_S)
    with _queue_lock:
        _waiting -= 1
    if not got:
        agent.LOG.write("coach_http", user_id=user_id, question=question, status=429, error="busy_timeout", **meta)
        return 429, {"error": "busy"}
    try:
        r = answerer(question, data, log_extra={"dataset": "app", **meta})
    except Exception as e:
        print(f"[coach] answer failed: {type(e).__name__}", file=sys.stderr)
        agent.LOG.write("coach_http", user_id=user_id, question=question, status=500, error="answer_failed", **meta)
        return 500, {"error": "answer_failed"}
    finally:
        _ask_lock.release()
    if r["answer"].startswith("[error]"):
        print(f"[coach] model error: {r['answer'][:120]}", file=sys.stderr)  # a short code and plain words
        agent.LOG.write("coach_http", user_id=user_id, question=question, status=502, error=r.get("error"),
                        run_id=r.get("run_id"), **meta)
        return 502, {"error": "model_error"}
    body = shape(r)
    agent.LOG.write("coach_http", user_id=user_id, question=question, answer=r["answer"], route=r["route"],
                    flags=r["flags"], wall_s=round(time.perf_counter() - t0, 3), run_id=r.get("run_id"), **meta)
    return 200, body


class Handler(BaseHTTPRequestHandler):
    server_version = "coach"

    def _send(self, status: int, body: dict) -> None:
        raw = json.dumps(body, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        try:
            self.wfile.write(raw)
        except (ConnectionError, OSError):
            pass  # the caller gave up waiting; nothing to report

    def log_message(self, fmt, *args) -> None:  # quiet: questions are private
        pass

    def do_GET(self) -> None:
        if self.path == "/health":
            self._send(200, health())
        else:
            self._send(404, {"error": "not_found"})

    def _drain(self) -> None:
        """Read and drop a small request body before answering without using it. Replying and closing while the
        client is still sending resets the connection (seen on Windows), so the client never sees the status."""
        try:
            size = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            return
        if 0 < size <= MAX_BODY_BYTES:
            self.rfile.read(size)

    def do_POST(self) -> None:
        if self.path != "/ask":
            self._drain()
            return self._send(404, {"error": "not_found"})
        expected = os.environ.get("COACH_SHARED_SECRET", "")
        given = self.headers.get("X-Coach-Secret", "")
        if not expected or not hmac.compare_digest(expected, given):
            self._drain()
            return self._send(401, {"error": "unauthorized"})
        try:
            size = int(self.headers.get("Content-Length", "0"))
            if not 0 < size <= MAX_BODY_BYTES:
                raise ValueError
            body = json.loads(self.rfile.read(size))
            user_id, question = body["userId"], body["question"]
            uat, persona = body.get("uat"), body.get("persona")
            if (not isinstance(user_id, int) or isinstance(user_id, bool) or user_id < 1
                    or not isinstance(question, str) or not 0 < len(question.strip()) <= MAX_QUESTION_CHARS):
                raise ValueError
            if uat is not None and (not isinstance(uat, dict)
                                    or type(uat.get("round")) is not int or uat["round"] not in (1, 2)
                                    or type(uat.get("tester_number")) is not int or uat["tester_number"] not in (1, 2, 3, 4)
                                    or not isinstance(uat.get("task_id"), str)
                                    or not re.fullmatch(r"UAT-(0[1-9]|1[01])", uat["task_id"])
                                    or not isinstance(uat.get("chat_id"), str)
                                    or not re.fullmatch(r"[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}", uat["chat_id"], re.I)
                                    or type(uat.get("attempt")) is not int or uat["attempt"] < 1):
                raise ValueError
            if persona is not None and (not isinstance(persona, str) or not re.fullmatch(r"[A-Z][a-z]+", persona)):
                raise ValueError
        except (ValueError, KeyError, TypeError):
            return self._send(400, {"error": "bad_request"})
        status, out = ask(user_id, question.strip(), uat=uat, persona=persona)
        self._send(status, out)


def serve(port: int | None = None) -> None:
    load_env()
    port = port or int(os.environ.get("COACH_PORT", "8765"))
    if not os.environ.get("COACH_SHARED_SECRET"):
        raise SystemExit("Set COACH_SHARED_SECRET in Harness/.env (python dev.py coach-secret creates one).")
    global _refresher_running
    _refresher_running = True
    threading.Thread(target=_refresh_status_forever, daemon=True).start()
    threading.Thread(target=warm_up, daemon=True).start()
    server = ThreadingHTTPServer((HOST, port), Handler)
    print(f"Coach listening on http://{HOST}:{port}  (Ctrl+C to stop)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("stopped")


if __name__ == "__main__":
    serve()

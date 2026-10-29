"""Synthetic end-to-end probe of the main user journey, over real HTTP.

upload -> confirm -> identify (share link) -> claim all items -> pay -> lock -> summary

Used as the post-deploy smoke test and as continuous synthetic traffic in dev, so
dashboards and alerts have data even with no real users. It talks to the app only
through HTTP, exactly like a browser would.
"""

from __future__ import annotations

import http.cookiejar
import io
import re
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from dataclasses import dataclass, field

PROBE_PARTICIPANT = "Probe"

# 8x8 white PNG; the demo extractor ignores the pixels.
_TINY_PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000080000000808020000004b6d29dc"
    "0000001549444154789c63fcffff3f0336c0845574d04a000056d4030d37eccca3"
    "0000000049454e44ae426082"
)


class ProbeError(RuntimeError):
    def __init__(self, step: str, detail: str) -> None:
        super().__init__(f"{step}: {detail}")
        self.step = step


@dataclass
class ProbeResult:
    ok: bool
    step: str
    duration_s: float
    detail: str = ""
    steps: list[str] = field(default_factory=list)


class _Session:
    def __init__(self, base_url: str, timeout: float) -> None:
        self.base = base_url.rstrip("/")
        self.timeout = timeout
        self.jar = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.jar))

    def _csrf(self) -> str:
        return next((c.value for c in self.jar if c.name == "csrftoken"), "")

    def request(self, method: str, path: str, data: bytes | None = None, headers=None):
        url = path if path.startswith("http") else f"{self.base}{path}"
        hdrs = {"Referer": f"{self.base}/", "User-Agent": "splitsnap-probe/1"}
        hdrs.update(headers or {})
        req = urllib.request.Request(url, data=data, method=method, headers=hdrs)
        with self.opener.open(req, timeout=self.timeout) as resp:
            return resp.status, resp.geturl(), resp.read().decode("utf-8", "replace")

    def get(self, path: str):
        return self.request("GET", path)

    def post_form(self, path: str, fields: dict[str, str]):
        body = urllib.parse.urlencode({"csrfmiddlewaretoken": self._csrf(), **fields}).encode()
        return self.request(
            "POST", path, body, {"Content-Type": "application/x-www-form-urlencoded"}
        )

    def post_file(self, path: str, field_name: str, filename: str, content: bytes):
        boundary = uuid.uuid4().hex
        buf = io.BytesIO()
        buf.write(
            f"--{boundary}\r\n"
            'Content-Disposition: form-data; name="csrfmiddlewaretoken"\r\n\r\n'
            f"{self._csrf()}\r\n"
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="{field_name}"; filename="{filename}"\r\n'
            "Content-Type: image/png\r\n\r\n".encode()
        )
        buf.write(content)
        buf.write(f"\r\n--{boundary}--\r\n".encode())
        return self.request(
            "POST",
            path,
            buf.getvalue(),
            {"Content-Type": f"multipart/form-data; boundary={boundary}"},
        )


def run_probe(base_url: str, timeout: float = 120.0) -> ProbeResult:
    s = _Session(base_url, timeout)
    t0 = time.monotonic()
    steps: list[str] = []

    def mark(name: str) -> str:
        steps.append(name)
        return name

    step = "start"
    try:
        step = mark("healthz")
        status, _, _ = s.get("/healthz")
        if status != 200:
            raise ProbeError(step, f"status {status}")

        step = mark("upload")
        s.get("/")  # sets the CSRF cookie
        _, admin_url, html = s.post_file("/", "receipt", "probe.png", _TINY_PNG)
        admin_path = urllib.parse.urlparse(admin_url).path
        if not re.match(r"^/b/[\w-]+/$", admin_path):
            raise ProbeError(step, "upload did not redirect to the admin page")
        total = re.search(r'name="printed_total" value="([\d.]+)"', html)
        if not total:
            raise ProbeError(step, "printed total not found on review page")

        step = mark("confirm")
        _, _, html = s.post_form(admin_path, {"action": "confirm"})
        share = re.search(r"/s/([\w-]+)/", html)
        if not share:
            raise ProbeError(step, "share link not shown after confirm")
        share_path = f"/s/{share.group(1)}/"

        step = mark("identify")
        _, _, html = s.post_form(share_path, {"action": "identify", "name": PROBE_PARTICIPANT})

        step = mark("claim")
        item_ids = sorted(set(re.findall(r'name="item_id" value="(\d+)"', html)))
        if not item_ids:
            raise ProbeError(step, "no line items to claim")
        for item_id in item_ids:
            s.post_form(share_path, {"action": "toggle_claim", "item_id": item_id})

        step = mark("pay")
        _, _, html = s.get(admin_path)
        pid = re.search(rf'<option value="(\d+)">{PROBE_PARTICIPANT}</option>', html)
        if not pid:
            raise ProbeError(step, "probe participant not found")
        s.post_form(
            admin_path,
            {"action": "add_payment", "participant_id": pid.group(1), "amount": total.group(1)},
        )

        step = mark("lock")
        _, _, html = s.post_form(admin_path, {"action": "lock"})
        if "Settlement" not in html:
            raise ProbeError(step, "bill did not lock")

        step = mark("summary")
        status, _, html = s.get(f"{share_path}summary")
        if status != 200 or "Settlement" not in html:
            raise ProbeError(step, f"summary unavailable (status {status})")
    except ProbeError as exc:
        return ProbeResult(False, exc.step, time.monotonic() - t0, str(exc), steps)
    except urllib.error.HTTPError as exc:
        return ProbeResult(False, step, time.monotonic() - t0, f"HTTP {exc.code}", steps)
    except OSError as exc:  # URLError, timeouts, connection refused
        return ProbeResult(False, step, time.monotonic() - t0, f"connection: {exc}", steps)

    return ProbeResult(True, "summary", time.monotonic() - t0, "", steps)

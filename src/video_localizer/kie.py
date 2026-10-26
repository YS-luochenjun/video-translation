from __future__ import annotations
from .timing import timed

import ipaddress
import json
import mimetypes
import socket
import uuid
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urljoin, urlparse
from urllib.request import HTTPRedirectHandler, Request, build_opener

from .common import WorkflowError, load_key, require
from .model_routing import require_current, require_remote_task, selected

API = "https://api.kie.ai"
# Official upload quickstart's example uses this dedicated upload host.
UPLOAD = "https://kieai.redpandaai.co/api/file-stream-upload"
# Explicit current endpoints, verified against KIE's public documentation.
# The old gemini-3-flash route repeatedly returned "channel is not supported".
AUDIO_MODELS = (selected('audio_analysis'), 'gemini-3.1-pro')


class ApiError(WorkflowError):
    def __init__(self, message, ambiguous=False, provider_response=None):
        super().__init__(message)
        self.ambiguous = ambiguous
        self.provider_response = provider_response


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class KieClient:
    def __init__(self, key=None, opener=None):
        self.key = key if key is not None else load_key()
        self.opener = opener or build_opener(NoRedirect)

    def _request(self, url, body=None, content_type="application/json", envelope=True, timeout=60):
        require(urlparse(url).hostname in ("api.kie.ai", "kieai.redpandaai.co"), "Unauthorized API host")
        from .budgets import authorize_request
        authorize_request(url, body)
        data = body if isinstance(body, bytes) else json.dumps(body).encode() if body is not None else None
        request = Request(url, data=data, headers={"Authorization": f"Bearer {self.key}",
                          "Content-Type": content_type, "User-Agent": "AdLocalizer/0.1"})
        try:
            with self.opener.open(request, timeout=timeout) as response:
                result = json.load(response)
        except HTTPError as exc:
            raise ApiError(f"KIE HTTP {exc.code}", ambiguous=body is not None and exc.code >= 500) from exc
        except (URLError, TimeoutError, OSError, ValueError) as exc:
            raise ApiError(f"KIE transport/response failure ({type(exc).__name__}); inspect provider log before resubmitting",
                           ambiguous=body is not None) from exc
        if ((envelope or "code" in result) and result.get("code") != 200) or result.get("success") is False:
            detail = str(result.get("msg", "request rejected")).replace(self.key, "[REDACTED]")
            safe_response = json.loads(json.dumps(result).replace(self.key, '[REDACTED]'))
            code = result.get('code')
            uncertain = body is not None and str(code).isdigit() and int(code) >= 500
            raise ApiError(f"KIE code {code}: {detail[:300]}", ambiguous=uncertain,
                           provider_response=safe_response)
        if not envelope:
            return result.get("data") if "choices" not in result and isinstance(result.get("data"), dict) else result
        return result.get("data")

    @timed('kie.analyze_audio')
    def analyze_audio(self, audio_url, prompt, model=None, *, run=None, model_authorization=None):
        model = model or selected('audio_analysis')
        require(model in AUDIO_MODELS, 'Unsupported audio analysis endpoint; new work uses the configured Flash model')
        from .model_routing import require_audio_analysis_model
        require_audio_analysis_model(model, run=run, authorization=model_authorization)
        # KIE's documented Gemini media structure uses image_url for audio too.
        urls = audio_url if isinstance(audio_url, list) else [audio_url]
        content = [{"type": "text", "text": prompt}]
        for index, url in enumerate(urls):
            label = "Audio file" if len(urls) == 1 else "Audio A: original source" if index == 0 else "Audio B: candidate"
            content.extend([{"type": "text", "text": label}, {"type": "image_url", "image_url": {"url": url}}])
        body = {
            "messages": [{"role": "user", "content": content}],
            "stream": False, "include_thoughts": False}
        result = self._request(API + f"/{model}/v1/chat/completions", body, envelope=False, timeout=180)
        require(isinstance(result, dict) and bool(result.get("choices")), "Audio analysis returned no choices")
        return result

    @timed('kie.credits')
    def credits(self):
        return self._request(API + "/api/v1/chat/credit")

    @timed('kie.create')
    def create(self, payload, *, run=None, model_authorization=None):
        require_remote_task(payload.get('model'), run=run, authorization=model_authorization)
        data = self._request(API + "/api/v1/jobs/createTask", payload)
        if not isinstance(data, dict) or not data.get("taskId"):
            raise ApiError("KIE accepted request but returned no taskId; inspect provider log", ambiguous=True)
        return data["taskId"]

    @timed('kie.status')
    def status(self, task_id):
        return self._request(API + "/api/v1/jobs/recordInfo?" + urlencode({"taskId": task_id}))

    @timed('kie.upload')
    def upload(self, path):
        path = Path(path)
        require(path.is_file() and path.stat().st_size <= 200 * 1024 * 1024, "Upload missing or larger than 200 MiB")
        boundary = uuid.uuid4().hex
        # Remote object names are random, avoiding user filenames and accidental overwrites.
        name = uuid.uuid4().hex + path.suffix.lower()
        prefix = (f'--{boundary}\r\nContent-Disposition: form-data; name="uploadPath"\r\n\r\n'
                  f'ad-localizer\r\n--{boundary}\r\nContent-Disposition: form-data; name="fileName"\r\n\r\n'
                  f'{name}\r\n--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{name}"\r\n'
                  f'Content-Type: {mimetypes.guess_type(name)[0] or "application/octet-stream"}\r\n\r\n').encode()
        data = self._request(UPLOAD, prefix + path.read_bytes() + f"\r\n--{boundary}--\r\n".encode(),
                             f"multipart/form-data; boundary={boundary}")
        require(isinstance(data, dict) and bool(data.get("downloadUrl")), "Upload response has no downloadUrl")
        return data["downloadUrl"]


def public_url(url):
    parsed = urlparse(url)
    require(parsed.scheme == "https" and bool(parsed.hostname) and not parsed.username and not parsed.password,
            "Media URL must use HTTPS without embedded credentials")
    require(parsed.port in (None, 443), "Only HTTPS port 443 is supported")
    try:
        addresses = socket.getaddrinfo(parsed.hostname, 443, type=socket.SOCK_STREAM)
    except OSError as exc:
        raise WorkflowError("Media host cannot be resolved") from exc
    require(bool(addresses) and all(ipaddress.ip_address(item[4][0]).is_global for item in addresses),
            "Private/loopback media URLs are not allowed")
    return url


@timed('kie.download')
def download(url, destination, max_bytes=500 * 1024 * 1024):
    """Unauthenticated media fetch; validate each redirect and never forward the API key."""
    opener = build_opener(NoRedirect)
    destination = Path(destination)
    require(not destination.exists(), "Download target already exists")
    temporary = destination.with_suffix(destination.suffix + ".part")
    try:
        for _ in range(4):
            public_url(url)
            try:
                response = opener.open(Request(url, headers={"User-Agent": "AdLocalizer/0.1"}), timeout=60)
                break
            except HTTPError as exc:
                if exc.code not in (301, 302, 303, 307, 308):
                    raise WorkflowError(f"Media download HTTP {exc.code}") from exc
                url = urljoin(url, exc.headers["Location"])
        else:
            raise WorkflowError("Too many media redirects")
        size = 0
        destination.parent.mkdir(parents=True, exist_ok=True)
        with response, temporary.open("wb") as stream:
            for block in iter(lambda: response.read(1024 * 1024), b""):
                size += len(block)
                require(size <= max_bytes, "Media exceeds download limit")
                stream.write(block)
        require(size > 0, "Empty downloaded media")
        temporary.replace(destination)
    finally:
        temporary.unlink(missing_ok=True)


def result_urls(status):
    if status.get("state") != "success":
        return []
    raw = status.get("resultJson", {})
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except ValueError as exc:
            raise WorkflowError("Invalid successful task resultJson") from exc
    urls = raw.get("resultUrls", []) if isinstance(raw, dict) else []
    require(isinstance(urls, list) and all(isinstance(url, str) for url in urls), "Invalid resultUrls")
    return urls


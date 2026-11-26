from __future__ import annotations
from .timing import timed

import ipaddress
import json
import mimetypes
import socket
import time
import uuid
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urljoin, urlparse
from urllib.request import HTTPRedirectHandler, Request, build_opener

from .common import WorkflowError, load_key, require
from .model_routing import audio_recovery_route, require_current, require_remote_task, selected
from .retry_activity import observe_request, reason

API = "https://api.kie.ai"
# Official upload quickstart's example uses this dedicated upload host.
UPLOAD = "https://kieai.redpandaai.co/api/file-stream-upload"
# Explicit current endpoints, verified against KIE's public documentation.
# The old gemini-3-flash route repeatedly returned "channel is not supported".
AUDIO_MODELS = (selected('audio_analysis'), audio_recovery_route('comparative_audio_review')['model'], 'gemini-3.1-pro')


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
        safe_read = body is None
        max_attempts = 3 if safe_read else 1
        transient_http = {408, 425, 429, 500, 502, 503, 504, 524}
        operation = {'credit': 'balance', 'recordInfo': 'status', 'createTask': 'model_submit',
                     'file-stream-upload': 'upload'}.get(urlparse(url).path.rsplit('/', 1)[-1], 'model_request')
        call_id = None
        previous_cause = None

        def failure(attempt, cause, outcome='failed'):
            nonlocal call_id, previous_cause
            call_id = call_id or uuid.uuid4().hex
            observe_request(call_id, attempt - 1, operation, cause, outcome)
            previous_cause = cause

        for attempt in range(1, max_attempts + 1):
            if call_id:
                observe_request(call_id, attempt - 1, operation, previous_cause, 'started')
            request = Request(url, data=data, headers={"Authorization": f"Bearer {self.key}",
                              "Content-Type": content_type, "User-Agent": "AdLocalizer/0.1"})
            try:
                with self.opener.open(request, timeout=min(timeout, 12) if safe_read else timeout) as response:
                    result = json.load(response)
                    if not isinstance(result, dict):
                        raise ValueError("Expected a KIE response object")
            except HTTPError as exc:
                provider_response = self._error_response(exc)
                uncertain = not safe_read and (exc.code == 408 or exc.code >= 500)
                failure(attempt, reason(exc.code), 'unknown' if uncertain else 'failed')
                if safe_read and exc.code in transient_http and attempt < max_attempts:
                    time.sleep(0.5 * (2 ** (attempt - 1)))
                    continue
                detail = self._error_detail(provider_response, exc.reason).replace(self.key, '[REDACTED]')
                raise ApiError(
                    f"KIE HTTP {exc.code}: {detail[:300]}",
                    ambiguous=uncertain,
                    provider_response=provider_response) from exc
            except (URLError, TimeoutError, OSError, ValueError) as exc:
                failure(attempt, 'invalid_response' if isinstance(exc, ValueError) else 'transport',
                        'failed' if safe_read else 'unknown')
                if safe_read and attempt < max_attempts:
                    time.sleep(0.5 * (2 ** (attempt - 1)))
                    continue
                raise ApiError(
                    f"KIE transport/response failure ({type(exc).__name__}); inspect provider log before resubmitting",
                    ambiguous=body is not None) from exc

            if ((envelope or "code" in result) and result.get("code") != 200) or result.get("success") is False:
                code = result.get('code')
                uncertain = not safe_read and str(code).isdigit() and (int(code) == 408 or int(code) >= 500)
                failure(attempt, reason(code), 'unknown' if uncertain else 'failed')
                if safe_read and str(code).isdigit() and int(code) in transient_http and attempt < max_attempts:
                    time.sleep(0.5 * (2 ** (attempt - 1)))
                    continue
                safe_response = self._redact(result)
                detail = self._error_detail(safe_response, "request rejected")
                raise ApiError(f"KIE code {code}: {detail[:300]}", ambiguous=uncertain,
                               provider_response=safe_response)
            if call_id:
                observe_request(call_id, attempt - 1, operation, previous_cause, 'success')
            if not envelope:
                return result.get("data") if "choices" not in result and isinstance(result.get("data"), dict) else result
            return result.get("data")

    def _redact(self, value):
        if value is None:
            return None
        try:
            return json.loads(json.dumps(value).replace(self.key, '[REDACTED]'))
        except (TypeError, ValueError):
            return {'raw': str(value).replace(self.key, '[REDACTED]')}

    def _error_response(self, error):
        try:
            raw = error.read()
            parsed = json.loads(raw.decode('utf-8', 'replace') if isinstance(raw, bytes) else raw)
            return self._redact(parsed)
        except (AttributeError, OSError, TypeError, ValueError):
            return self._redact({'http_status': error.code, 'reason': str(error.reason)})

    @staticmethod
    def _error_detail(response, fallback):
        if isinstance(response, dict):
            return str(response.get('msg') or response.get('message') or response.get('error') or fallback)
        return str(fallback)

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
        backup = audio_recovery_route('comparative_audio_review')
        if model == backup['model']:
            body['reasoning_effort'] = backup['reasoning_effort']
        result = self._request(API + f"/{model}/v1/chat/completions", body, envelope=False, timeout=180)
        require(isinstance(result, dict) and bool(result.get("choices")), "Audio analysis returned no choices")
        return result

    @timed('kie.transcribe_audio')
    def transcribe_audio(self, audio_url):
        route = audio_recovery_route('transcription_evidence')
        payload = {'model': route['model'], 'input': {'audio_url': audio_url, 'timestamps': True}}
        data = self._request(API + "/api/v1/jobs/createTask", payload)
        if not isinstance(data, dict) or not data.get('taskId'):
            raise ApiError("KIE accepted transcription but returned no taskId; inspect provider log", ambiguous=True)
        return data['taskId']

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
def download(url, destination, max_bytes=500 * 1024 * 1024, *, fixed_https_origin=None):
    """Unauthenticated media fetch; validate each redirect and never forward the API key."""
    opener = build_opener(NoRedirect)
    destination = Path(destination)
    require(not destination.exists(), "Download target already exists")
    temporary = destination.with_suffix(destination.suffix + ".part")
    try:
        for _ in range(4):
            if fixed_https_origin:
                parsed = urlparse(url)
                require(parsed.scheme == 'https' and parsed.netloc == fixed_https_origin,
                        'Media URL does not match the fixed HTTPS origin')
            else:
                public_url(url)
            try:
                response = opener.open(Request(url, headers={"User-Agent": "AdLocalizer/0.1"}), timeout=60)
                break
            except HTTPError as exc:
                if fixed_https_origin or exc.code not in (301, 302, 303, 307, 308):
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


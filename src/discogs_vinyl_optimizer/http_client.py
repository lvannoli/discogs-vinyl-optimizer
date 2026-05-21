from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urljoin
from urllib.request import Request, urlopen


class DiscogsHttpError(RuntimeError):
    pass


class DiscogsMethodError(ValueError):
    pass


@dataclass(frozen=True)
class DiscogsResponse:
    status: int
    headers: dict[str, str]
    body: bytes

    def json(self) -> Any:
        return json.loads(self.body.decode("utf-8"))


class DiscogsClient:
    def __init__(
        self,
        token: str | None = None,
        user_agent: str = "DiscogsVinylOptimizer/0.1",
        base_url: str = "https://api.discogs.com",
        timeout_seconds: int = 30,
        min_delay_seconds: float = 1.0,
        max_retries: int = 3,
    ) -> None:
        self.token = token
        self.user_agent = user_agent
        self.base_url = base_url.rstrip("/") + "/"
        self.timeout_seconds = timeout_seconds
        self.min_delay_seconds = min_delay_seconds
        self.max_retries = max_retries
        self._last_request_at = 0.0

    def request(self, method: str, path_or_url: str, params: dict[str, Any] | None = None) -> DiscogsResponse:
        if method.upper() != "GET":
            raise DiscogsMethodError("DiscogsClient only allows GET requests.")

        url = self._build_url(path_or_url, params)
        for attempt in range(self.max_retries + 1):
            self._throttle()
            request = Request(url, method="GET", headers=self._headers())
            try:
                with urlopen(request, timeout=self.timeout_seconds) as response:
                    body = response.read()
                    headers = {key.lower(): value for key, value in response.headers.items()}
                    return DiscogsResponse(status=response.status, headers=headers, body=body)
            except HTTPError as exc:
                body = exc.read().decode("utf-8", errors="replace")
                if exc.code == 429 and attempt < self.max_retries:
                    time.sleep(self._retry_after_seconds(exc, attempt))
                    continue
                raise DiscogsHttpError(f"Discogs GET failed with HTTP {exc.code}: {body}") from exc
            except URLError as exc:
                raise DiscogsHttpError(f"Discogs GET failed: {exc.reason}") from exc
        raise DiscogsHttpError("Discogs GET failed after retries.")

    def get_json(self, path_or_url: str, params: dict[str, Any] | None = None) -> Any:
        return self.request("GET", path_or_url, params=params).json()

    def _build_url(self, path_or_url: str, params: dict[str, Any] | None) -> str:
        if path_or_url.startswith(("http://", "https://")):
            url = path_or_url
        else:
            url = urljoin(self.base_url, path_or_url.lstrip("/"))
        if not params:
            return url
        separator = "&" if "?" in url else "?"
        return f"{url}{separator}{urlencode(params, doseq=True)}"

    def _headers(self) -> dict[str, str]:
        headers = {
            "Accept": "application/json",
            "User-Agent": self.user_agent,
        }
        if self.token:
            headers["Authorization"] = f"Discogs token={self.token}"
        return headers

    def _throttle(self) -> None:
        elapsed = time.monotonic() - self._last_request_at
        if elapsed < self.min_delay_seconds:
            time.sleep(self.min_delay_seconds - elapsed)
        self._last_request_at = time.monotonic()

    def _retry_after_seconds(self, exc: HTTPError, attempt: int) -> float:
        retry_after = exc.headers.get("Retry-After") if exc.headers else None
        if retry_after:
            try:
                return max(float(retry_after), self.min_delay_seconds)
            except ValueError:
                pass
        return max(self.min_delay_seconds * (attempt + 2), 5.0)

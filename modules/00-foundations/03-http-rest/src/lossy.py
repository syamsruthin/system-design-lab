"""
A network that loses responses: the request reaches the server and the work is done,
but the reply never makes it back. From the client's side, that looks exactly like a
request that never arrived, so all it can do is retry. Whether the retry is harmless
depends on the method.
"""
from __future__ import annotations

import random

import httpx


class LossyTransport(httpx.BaseTransport):
    def __init__(self, drop: float, seed: int):
        self._inner = httpx.HTTPTransport()
        self._rng = random.Random(seed)  # seeded: the same responses get lost on every run
        self.drop = drop
        self.sent = 0  # requests that actually reached the server

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        self.sent += 1
        response = self._inner.handle_request(request)
        response.read()  # the server has fully answered...
        if self._rng.random() < self.drop:
            response.close()
            raise httpx.ReadTimeout("response lost on the way back", request=request)  # ...but we never hear it
        return response

    def close(self) -> None:
        self._inner.close()


def send_with_retries(client: httpx.Client, method: str, url: str, body: dict, attempts: int = 10) -> httpx.Response:
    """What most clients do on a timeout: try again. Safe only if the method is idempotent."""
    for _ in range(attempts):
        try:
            return client.request(method, url, json=body)
        except httpx.TimeoutException:
            continue
    raise TimeoutError(f"{method} {url}: no response after {attempts} attempts")

"""
A real asyncio service, and two ways to load-test it.

The service has a fixed number of workers (an asyncio.Semaphore) and really waits for each
request's service time. It can be told to stall for a while, the way a garbage-collection
pause or a blocked disk freezes a real process.

The two load generators differ in one way that matters enormously:

    open loop    requests are sent on a fixed schedule (like real users, who don't wait for
                 each other). Latency is measured from when a request *should* have been sent.
    closed loop  each client sends its next request only after the previous reply arrives
                 (how most simple benchmarks work). During a stall the clients stop sending,
                 so the stall shows up as a few slow samples instead of many.
                 This is "coordinated omission".
"""
from __future__ import annotations

import asyncio

from .workload import Sampler


class Service:
    def __init__(self, workers: int, service: Sampler):
        self._slots = asyncio.Semaphore(workers)  # at most `workers` requests in service at once
        self._service = service
        self.stall: tuple[float, float] | None = None  # (from, until), in event-loop time

    async def handle(self) -> None:
        loop = asyncio.get_running_loop()
        async with self._slots:  # queue here when every worker is busy
            if self.stall and self.stall[0] <= loop.time() < self.stall[1]:
                await asyncio.sleep(self.stall[1] - loop.time())  # frozen: nothing gets served
            await asyncio.sleep(self._service())


async def open_loop(service: Service, rate: float, duration: float) -> list[float]:
    loop = asyncio.get_running_loop()
    start, latencies, tasks = loop.time(), [], []

    async def one(intended: float) -> None:
        await service.handle()
        latencies.append(loop.time() - intended)  # from the planned send time, not the actual one

    i = 0
    while (intended := start + i / rate) < start + duration:
        await asyncio.sleep(max(0.0, intended - loop.time()))
        tasks.append(asyncio.create_task(one(intended)))
        i += 1
    await asyncio.gather(*tasks)
    return latencies


async def closed_loop(service: Service, clients: int, duration: float) -> list[float]:
    loop = asyncio.get_running_loop()
    stop, latencies = loop.time() + duration, []

    async def client() -> None:
        while loop.time() < stop:
            sent = loop.time()
            await service.handle()  # the client waits here, so it can't notice what it didn't send
            latencies.append(loop.time() - sent)

    await asyncio.gather(*(client() for _ in range(clients)))
    return latencies


def measure(mode: str, service_factory: Sampler, workers: int, duration: float, rate: float, clients: int,
            stall: tuple[float, float] | None) -> list[float]:
    """Run one load test from scratch. `stall` is (seconds after start, how long) or None."""
    async def run() -> list[float]:
        service = Service(workers, service_factory)
        now = asyncio.get_running_loop().time()
        if stall:
            service.stall = (now + stall[0], now + stall[0] + stall[1])
        if mode == "open":
            return await open_loop(service, rate, duration)
        return await closed_loop(service, clients, duration)

    return asyncio.run(run())

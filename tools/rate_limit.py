"""Простой in-memory rate-limit (скользящее окно) для защиты от спама/злоупотреблений.

Однопроцессный бот → хватает словаря в памяти (сбрасывается при рестарте,
это приемлемо). Ключ — обычно отправитель (@username)."""
import time
from collections import defaultdict, deque

_events: dict[str, deque] = defaultdict(deque)


def allow(key: str, max_events: int, window_sec: int) -> bool:
    """True, если под ключом ещё не превышен лимит max_events за window_sec.
    Считает попытку (записывает время) только когда разрешает."""
    now = time.monotonic()
    dq = _events[key]
    while dq and now - dq[0] > window_sec:
        dq.popleft()
    if len(dq) >= max_events:
        return False
    dq.append(now)
    return True

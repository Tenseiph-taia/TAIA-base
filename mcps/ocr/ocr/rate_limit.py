import time
from collections import defaultdict
from .config import RATE_LIMIT_REQUESTS, RATE_LIMIT_WINDOW

buckets = defaultdict(list)


def check_rate_limit(ip: str) -> bool:
    now = time.time()
    window = buckets[ip]

    while window and window[0] < now - RATE_LIMIT_WINDOW:
        window.pop(0)

    if len(window) >= RATE_LIMIT_REQUESTS:
        return False

    window.append(now)
    return True
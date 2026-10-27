from contextlib import contextmanager
from time import perf_counter_ns


@contextmanager
def measure(timings, name):
    started = perf_counter_ns()
    try:
        yield
    finally:
        elapsed = perf_counter_ns() - started
        timings[name] = timings.get(name, 0) + elapsed
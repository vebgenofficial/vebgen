# backend/src/core/performance_monitor.py
import time
import logging
from functools import wraps
from collections import defaultdict
import threading
from typing import Any, Callable

logger = logging.getLogger(__name__)

class PerformanceMonitor:
    """
    A singleton class to monitor and report on the performance of key functions.

    This monitor uses a decorator (`@time_function`) to record execution times
    and aggregates metrics like call count, total time, average time, and max time.
    It is thread-safe.
    """
    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super(PerformanceMonitor, cls).__new__(cls)
                cls._instance.metrics = defaultdict(lambda: {'calls': 0, 'total_time': 0.0, 'max_time': 0.0})
                cls._instance.enabled = True # Can be controlled externally
            return cls._instance

    def record(self, name: str, duration: float):
        """Records a single metric for a function call."""
        if not self.enabled:
            return
        with self._lock:
            self.metrics[name]['calls'] += 1
            self.metrics[name]['total_time'] += duration
            if duration > self.metrics[name]['max_time']:
                self.metrics[name]['max_time'] = duration

    def get_report(self) -> str:
        """Generates a formatted string report of all recorded metrics."""
        if not self.metrics:
            return "No performance metrics recorded."
        
        report_lines = ["--- Performance Report ---"]
        # Sort by total time spent, descending
        sorted_metrics = sorted(self.metrics.items(), key=lambda item: item[1]['total_time'], reverse=True)

        for name, data in sorted_metrics:
            calls = data['calls']
            total_time = data['total_time']
            avg_time = total_time / calls if calls > 0 else 0
            max_time = data['max_time']
            report_lines.append(
                f"- {name:<40} "
                f"Calls={calls:<5} | "
                f"Total={total_time:<8.4f}s | "
                f"Avg={avg_time:<8.4f}s | "
                f"Max={max_time:<8.4f}s"
            )
        return "\n".join(report_lines)

    def log_report(self):
        """Logs the performance report to the standard logger."""
        logger.info(self.get_report())

    def reset(self):
        """Clears all recorded metrics."""
        with self._lock:
            self.metrics.clear()

# Singleton instance for global access
performance_monitor = PerformanceMonitor()

def time_function(func: Callable) -> Callable:
    """A decorator to time the execution of a function and record it."""
    @wraps(func)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        start_time = time.monotonic()
        result = func(*args, **kwargs)
        end_time = time.monotonic()
        duration = end_time - start_time
        
        # Use a qualified name for methods
        if args and hasattr(args[0], '__class__'):
            func_name = f"{args[0].__class__.__name__}.{func.__name__}"
        else:
            func_name = func.__name__
            
        performance_monitor.record(func_name, duration)
        return result
    return wrapper
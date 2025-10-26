# backend/src/core/tests/test_performance_monitor.py
import pytest
import threading
import time
import re
from unittest.mock import patch

from src.core.performance_monitor import PerformanceMonitor, time_function, performance_monitor

# --- Fixture to ensure a clean monitor for each test ---

@pytest.fixture(autouse=True)
def reset_monitor():
    """Resets the singleton performance_monitor before each test."""
    performance_monitor.reset()
    performance_monitor.enabled = True
    yield
    performance_monitor.reset()

# --- Test Cases for PerformanceMonitor Class ---

class TestPerformanceMonitor:
    """Tests for the PerformanceMonitor singleton class."""

    def test_singleton_instance(self):
        """Tests that multiple instantiations return the same object."""
        monitor1 = PerformanceMonitor()
        monitor2 = PerformanceMonitor()
        assert monitor1 is monitor2
        assert monitor1 is performance_monitor

    def test_record_single_call(self):
        """Tests that a single call to record() correctly initializes metrics."""
        performance_monitor.record("test_func", 0.1)
        metrics = performance_monitor.metrics["test_func"]
        assert metrics['calls'] == 1
        assert metrics['total_time'] == pytest.approx(0.1)
        assert metrics['max_time'] == pytest.approx(0.1)

    def test_record_multiple_calls(self):
        """Tests that multiple calls correctly aggregate metrics."""
        performance_monitor.record("test_func", 0.1)
        performance_monitor.record("test_func", 0.2)
        metrics = performance_monitor.metrics["test_func"]
        assert metrics['calls'] == 2
        assert metrics['total_time'] == pytest.approx(0.3)

    def test_record_updates_max_time(self):
        """Tests that max_time is correctly updated."""
        performance_monitor.record("test_func", 0.2)
        performance_monitor.record("test_func", 0.1)
        performance_monitor.record("test_func", 0.3)
        metrics = performance_monitor.metrics["test_func"]
        assert metrics['max_time'] == pytest.approx(0.3)

    def test_reset_clears_metrics(self):
        """Tests that reset() clears all recorded metrics."""
        performance_monitor.record("test_func", 0.1)
        assert "test_func" in performance_monitor.metrics
        performance_monitor.reset()
        assert not performance_monitor.metrics

    def test_disabled_monitor_does_not_record(self):
        """Tests that no metrics are recorded when the monitor is disabled."""
        performance_monitor.enabled = False
        performance_monitor.record("test_func", 0.1)
        assert "test_func" not in performance_monitor.metrics

    def test_thread_safety(self):
        """Tests that concurrent calls to record() are handled correctly."""
        num_threads = 10
        calls_per_thread = 100
        duration_per_call = 0.001
        threads = []

        def worker():
            for _ in range(calls_per_thread):
                performance_monitor.record("concurrent_func", duration_per_call)

        for _ in range(num_threads):
            thread = threading.Thread(target=worker)
            threads.append(thread)
            thread.start()

        for thread in threads:
            thread.join()

        metrics = performance_monitor.metrics["concurrent_func"]
        expected_calls = num_threads * calls_per_thread
        expected_total_time = expected_calls * duration_per_call

        assert metrics['calls'] == expected_calls
        assert metrics['total_time'] == pytest.approx(expected_total_time)


class TestGetReport:
    """Tests for the get_report() method."""

    def test_get_report_empty(self):
        """Tests the report format when no metrics are recorded."""
        report = performance_monitor.get_report()
        assert report == "No performance metrics recorded."

    def test_get_report_sorting_and_format(self):
        """Tests that the report is sorted by total_time and formatted correctly."""
        performance_monitor.record("fast_func", 0.1)
        performance_monitor.record("slow_func", 0.5)
        performance_monitor.record("slow_func", 0.6) # Total time = 1.1

        report = performance_monitor.get_report()
        report_lines = report.split('\n')

        assert "--- Performance Report ---" in report_lines[0]
        assert "slow_func" in report_lines[1] # slow_func should be first
        assert "fast_func" in report_lines[2] # fast_func should be second
        # Use regex to be resilient to whitespace changes from formatting
        assert re.search(r"Total=\s*1\.1000\s*s", report_lines[1])
        assert re.search(r"Avg=\s*0\.5500\s*s", report_lines[1])
        assert re.search(r"Max=\s*0\.6000\s*s", report_lines[1])


# --- Test Cases for @time_function Decorator ---

class TestTimeFunctionDecorator:
    """Tests for the @time_function decorator."""

    def test_decorator_records_metric(self):
        """Tests that the decorator calls performance_monitor.record."""
        @time_function
        def my_timed_function():
            time.sleep(0.01)
            return "done"

        result = my_timed_function()

        assert result == "done"
        assert "my_timed_function" in performance_monitor.metrics
        metrics = performance_monitor.metrics["my_timed_function"]
        assert metrics['calls'] == 1
        assert metrics['total_time'] > 0.009

    def test_decorator_on_class_method(self):
        """Tests that the decorator correctly names metrics for class methods."""
        class MyClass:
            @time_function
            def my_method(self):
                return "method_done"

        instance = MyClass()
        result = instance.my_method()

        assert result == "method_done"
        # The decorator should format the name as "ClassName.method_name"
        assert "MyClass.my_method" in performance_monitor.metrics
        metrics = performance_monitor.metrics["MyClass.my_method"]
        assert metrics['calls'] == 1
from muletrace.perf import measure, peak_memory_mb


def test_measure_records_time_and_memory() -> None:
    with measure() as measurement:
        payload = bytearray(8 * 1024 * 1024)
    assert len(payload) == 8 * 1024 * 1024
    assert measurement.seconds >= 0
    assert measurement.peak_memory_mb >= 8
    assert peak_memory_mb() >= measurement.peak_memory_mb - 1

import muletrace


def test_package_exposes_a_version_string() -> None:
    assert isinstance(muletrace.__version__, str)
    assert muletrace.__version__.count(".") >= 2

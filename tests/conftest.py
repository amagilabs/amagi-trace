import json
import os
import zipfile

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RESULTS = os.path.join(ROOT, "examples", "test-results")


@pytest.fixture(scope="session")
def results_dir():
    return RESULTS


@pytest.fixture(scope="session")
def checkout_zip():
    return os.path.join(RESULTS, "shop-checkout-shows-confirmation", "trace.zip")


@pytest.fixture(scope="session")
def passing_zip():
    return os.path.join(RESULTS, "shop-heading-visible", "trace.zip")


@pytest.fixture(scope="session")
def coupon_zip():
    return os.path.join(RESULTS, "shop-coupon-call-is-aborted-and-page-throws", "trace.zip")


@pytest.fixture(scope="session")
def timeout_zip():
    return os.path.join(RESULTS, "shop-missing-button-click-times-out", "trace.zip")


def make_trace(path, test_events, browser_events, network=()):
    """Write a minimal synthetic trace.zip (same layout Playwright produces)."""
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("test.trace", "\n".join(json.dumps(e) for e in test_events))
        z.writestr("1-trace.trace", "\n".join(json.dumps(e) for e in browser_events))
        z.writestr("1-trace.network", "\n".join(json.dumps(e) for e in network))
    return str(path)

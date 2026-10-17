"""The integration must accept exactly the addresses the app accepts.

The rule lives in two languages (TypeScript in the app, Python here). Both test
suites read ``shared_url_vectors.json``; changing the rule on one side only
breaks a test instead of silently producing pairing links the app rejects.
"""

import json
from pathlib import Path

import pytest

from custom_components.stormguard.pairing import app_accepts_base_url

VECTORS_FILE = Path(__file__).parent / "shared_url_vectors.json"
VECTORS = json.loads(VECTORS_FILE.read_text(encoding="utf-8"))


@pytest.mark.parametrize("url", VECTORS["accepted"])
def test_app_accepts(url: str) -> None:
    assert app_accepts_base_url(url)


@pytest.mark.parametrize("url", VECTORS["rejected"])
def test_app_rejects(url: str) -> None:
    assert not app_accepts_base_url(url)

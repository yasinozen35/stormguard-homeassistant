"""Static checks: manifest, HACS metadata and translations.

`scripts/test.sh` additionally runs Home Assistant's real `hassfest`
validator; these checks keep the basics enforced in plain pytest.
"""

import json
from pathlib import Path
import re
from typing import Any

import pytest

from custom_components.stormguard.const import DOMAIN, PROFILES

ROOT = Path(__file__).parents[1]
COMPONENT = ROOT / "custom_components" / DOMAIN
REPO = "https://github.com/yasinozen35/stormguard-homeassistant"


def load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def test_manifest() -> None:
    manifest = load(COMPONENT / "manifest.json")
    keys = list(manifest)
    # hassfest: domain, name first, then alphabetical.
    assert keys[:2] == ["domain", "name"]
    assert keys[2:] == sorted(keys[2:])
    assert manifest["domain"] == DOMAIN
    assert manifest["codeowners"] == ["@yasinozen35"]
    assert manifest["config_flow"] is True
    assert manifest["dependencies"] == ["webhook"]
    assert manifest["iot_class"] == "local_push"
    assert manifest["documentation"] == REPO
    assert manifest["issue_tracker"] == f"{REPO}/issues"
    assert re.fullmatch(r"\d+\.\d+\.\d+", manifest["version"])


def test_hacs_json() -> None:
    hacs = load(ROOT / "hacs.json")
    assert hacs["name"] == "StormGuard"
    assert re.fullmatch(r"\d{4}\.\d+\.\d+", hacs["homeassistant"])
    assert set(hacs) <= {
        "name",
        "homeassistant",
        "render_readme",
        "country",
        "hacs",
        "zip_release",
        "filename",
        "hide_default_branch",
        "content_in_root",
        "persistent_directory",
    }


def _flatten(data: Any, prefix: str = "") -> dict[str, str]:
    out: dict[str, str] = {}
    if isinstance(data, dict):
        for key, value in data.items():
            out.update(_flatten(value, f"{prefix}.{key}" if prefix else key))
    else:
        out[prefix] = data
    return out


def test_strings_equal_english() -> None:
    assert load(COMPONENT / "strings.json") == load(COMPONENT / "translations" / "en.json")


@pytest.mark.parametrize("lang", ["en", "tr"])
def test_translation_keys_and_placeholders(lang: str) -> None:
    strings = _flatten(load(COMPONENT / "strings.json"))
    other = _flatten(load(COMPONENT / "translations" / f"{lang}.json"))
    assert set(strings) == set(other)
    for key, text in strings.items():
        assert set(re.findall(r"{(\w+)}", text)) == set(re.findall(r"{(\w+)}", other[key])), key


def test_every_profile_has_a_name() -> None:
    strings = load(COMPONENT / "strings.json")
    assert set(strings["entity"]["binary_sensor"]) == set(PROFILES)

"""Optional official Hermes SecretSource conformance integration.

Run when pytest is available in the development environment:
PYTHONPATH=/usr/local/lib/hermes-agent pytest -q tests/test_conformance.py
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


PLUGIN = Path(__file__).parents[1] / "__init__.py"
_HERMES_CONFORMANCE = Path("/usr/local/lib/hermes-agent/tests/secret_sources/conformance.py")
_conformance_spec = importlib.util.spec_from_file_location("hermes_secret_source_conformance", _HERMES_CONFORMANCE)
assert _conformance_spec is not None and _conformance_spec.loader is not None
_conformance_module = importlib.util.module_from_spec(_conformance_spec)
_conformance_spec.loader.exec_module(_conformance_module)
SecretSourceConformance = _conformance_module.SecretSourceConformance


def _load():
    spec = importlib.util.spec_from_file_location(
        "hermes_locker_conformance", PLUGIN, submodule_search_locations=[str(PLUGIN.parent)]
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TestLockerConformance(SecretSourceConformance):
    @pytest.fixture
    def source(self):
        return _load().LockerSecretSource()

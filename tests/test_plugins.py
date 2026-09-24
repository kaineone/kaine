# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Unit tests for ``kaine.plugins``."""
import logging

import pytest

from kaine.config import ConfigShapeError, validate_config_shape
from kaine.experiment.run_context import mint_run_context
from kaine.plugins import PluginError, load_plugins


class FakeDist:
    def __init__(self, name: str, version: str):
        self.name = name
        self.version = version


class FakeEP:
    def __init__(self, name: str, factory, dist=None):
        self.name = name
        self._factory = factory
        self.dist = dist

    def load(self):
        return self._factory


class _NeverLoadEP:
    name = "never"
    dist = None

    def load(self):
        raise AssertionError("entry point should never be loaded")


class _ConfigurablePlugin:
    def __init__(self, name, seams, injections=None, maker=None):
        self.name = name
        self._seams = frozenset(seams)
        self._injections = injections or {}
        self._maker = maker
        self.inject_calls = 0
        self.make_calls = 0
        self.seen_config = None

    def seams(self, config):
        self.seen_config = config
        return self._seams

    def injections(self, module, config):
        self.inject_calls += 1
        return self._injections.get(module, {})

    def make_oscillator(self, module, config, defaults):
        self.make_calls += 1
        if callable(self._maker):
            return self._maker(module, config, defaults)
        return self._maker


def _eps(*eps):
    return lambda group="kaine.plugins": list(eps)


def test_no_plugins_section_does_not_call_entry_points():
    called = []
    lp = load_plugins(
        {},
        known_modules=["chronos"],
        entry_points=lambda group: called.append(group) or [_NeverLoadEP()],
    )
    assert not lp
    assert called == []


def test_installed_but_not_enabled_is_not_loaded():
    lp = load_plugins(
        {"plugins": {"enabled": []}},
        known_modules=["chronos"],
        entry_points=_eps(_NeverLoadEP()),
    )
    assert not lp
    assert lp.manifest_entry() == {}


def test_missing_plugin_raises():
    with pytest.raises(PluginError, match="missing"):
        load_plugins(
            {"plugins": {"enabled": ["missing"]}},
            known_modules=["chronos"],
            entry_points=_eps(),
        )


def test_duplicate_entry_point_name_raises():
    ep1 = FakeEP("dup", object, FakeDist("a", "1"))
    ep2 = FakeEP("dup", object, FakeDist("b", "2"))
    with pytest.raises(PluginError, match="dup"):
        load_plugins(
            {"plugins": {"enabled": ["dup"]}},
            known_modules=["chronos"],
            entry_points=_eps(ep1, ep2),
        )


def test_entry_point_load_failure_raises():
    class BadEP:
        name = "bad"
        dist = None

        def load(self):
            raise ImportError("cannot import")

    with pytest.raises(PluginError, match="bad"):
        load_plugins(
            {"plugins": {"enabled": ["bad"]}},
            known_modules=["chronos"],
            entry_points=_eps(BadEP()),
        )


def test_factory_failure_raises():
    def boom():
        raise RuntimeError("boom")

    with pytest.raises(PluginError, match="bad"):
        load_plugins(
            {"plugins": {"enabled": ["bad"]}},
            known_modules=["chronos"],
            entry_points=_eps(FakeEP("bad", boom)),
        )


def test_seams_failure_raises():
    class P:
        name = "bad"

        def seams(self, config):
            raise ValueError("bad seams")

        def injections(self, module, config):
            return {}

    with pytest.raises(PluginError, match="bad"):
        load_plugins(
            {"plugins": {"enabled": ["bad"]}},
            known_modules=["chronos"],
            entry_points=_eps(FakeEP("bad", P)),
        )


def test_seams_non_set_raises():
    class P:
        def seams(self, config):
            return ["chronos.network"]

        def injections(self, module, config):
            return {}

    with pytest.raises(PluginError, match="bad"):
        load_plugins(
            {"plugins": {"enabled": ["bad"]}},
            known_modules=["chronos"],
            entry_points=_eps(FakeEP("bad", P)),
        )


def test_unknown_seam_raises():
    p = _ConfigurablePlugin("bad", {"chronos.cfc_units"})
    with pytest.raises(PluginError, match="chronos\\.cfc_units"):
        load_plugins(
            {"plugins": {"enabled": ["bad"]}},
            known_modules=["chronos"],
            entry_points=_eps(FakeEP("bad", lambda: p)),
        )


def test_unknown_oscillator_module_raises():
    p = _ConfigurablePlugin("bad", {"oscillator.unknown"})
    with pytest.raises(PluginError, match="oscillator\\.unknown"):
        load_plugins(
            {"plugins": {"enabled": ["bad"]}},
            known_modules=["chronos"],
            entry_points=_eps(FakeEP("bad", lambda: p)),
        )


def test_two_plugins_same_seam_raises():
    p1 = _ConfigurablePlugin("p1", {"chronos.network"})
    p2 = _ConfigurablePlugin("p2", {"chronos.network"})
    with pytest.raises(PluginError, match="chronos\\.network"):
        load_plugins(
            {"plugins": {"enabled": ["p1", "p2"]}},
            known_modules=["chronos"],
            entry_points=_eps(
                FakeEP("p1", lambda: p1),
                FakeEP("p2", lambda: p2),
            ),
        )


def test_oscillator_seam_when_layer_off_raises():
    p = _ConfigurablePlugin("bad", {"oscillator.chronos"})
    with pytest.raises(PluginError, match="oscillator\\.chronos"):
        load_plugins(
            {"plugins": {"enabled": ["bad"]}},
            known_modules=["chronos"],
            entry_points=_eps(FakeEP("bad", lambda: p)),
        )


def test_oscillator_seam_when_layer_on_loads():
    p = _ConfigurablePlugin("good", {"oscillator.chronos"})
    lp = load_plugins(
        {"plugins": {"enabled": ["good"]}, "oscillator": {"enabled": True}},
        known_modules=["chronos"],
        entry_points=_eps(FakeEP("good", lambda: p)),
    )
    assert lp
    assert lp.declares_oscillator("chronos")


def test_injections_for_returns_merged_values_and_logs(caplog):
    p = _ConfigurablePlugin(
        "good",
        {"chronos.network", "soma.forward_model"},
        {
            "chronos": {"network": "chronos-model"},
            "soma": {"forward_model": "soma-model"},
        },
    )
    lp = load_plugins(
        {"plugins": {"enabled": ["good"]}},
        known_modules=["chronos", "soma"],
        entry_points=_eps(FakeEP("good", lambda: p)),
    )
    with caplog.at_level(logging.WARNING, logger="kaine.plugins"):
        assert lp.injections_for("chronos") == {"network": "chronos-model"}
        assert lp.injections_for("soma") == {"forward_model": "soma-model"}
    logs = [rec.message for rec in caplog.records]
    assert "plugin good fills chronos.network" in logs
    assert "plugin good fills soma.forward_model" in logs


def test_injections_for_undeclared_key_raises():
    p = _ConfigurablePlugin("bad", {"chronos.network"}, {"chronos": {"network": 1, "extra": 2}})
    lp = load_plugins(
        {"plugins": {"enabled": ["bad"]}},
        known_modules=["chronos"],
        entry_points=_eps(FakeEP("bad", lambda: p)),
    )
    with pytest.raises(PluginError, match="extra"):
        lp.injections_for("chronos")


def test_injections_for_missing_declared_key_raises():
    p = _ConfigurablePlugin("bad", {"chronos.network"})
    lp = load_plugins(
        {"plugins": {"enabled": ["bad"]}},
        known_modules=["chronos"],
        entry_points=_eps(FakeEP("bad", lambda: p)),
    )
    with pytest.raises(PluginError, match="chronos\\.network"):
        lp.injections_for("chronos")


def test_injections_for_module_with_no_seam_does_not_call_plugin():
    p = _ConfigurablePlugin("p", {"chronos.network"})
    lp = load_plugins(
        {"plugins": {"enabled": ["p"]}},
        known_modules=["chronos", "soma"],
        entry_points=_eps(FakeEP("p", lambda: p)),
    )
    assert lp.injections_for("soma") == {}
    assert p.inject_calls == 0


def test_injections_for_is_called_fresh_each_time():
    p = _ConfigurablePlugin("p", {"chronos.network"}, {"chronos": {"network": object()}})
    lp = load_plugins(
        {"plugins": {"enabled": ["p"]}},
        known_modules=["chronos"],
        entry_points=_eps(FakeEP("p", lambda: p)),
    )
    a = lp.injections_for("chronos")
    b = lp.injections_for("chronos")
    c = lp.injections_for("chronos")
    assert p.inject_calls == 3
    assert a is not b and b is not c


def test_oscillator_for_declared_returns_object():
    expected = object()

    def maker(module, config, defaults):
        assert module == "chronos"
        assert config == {"x": 1}
        assert defaults == {"d": 2}
        return expected

    p = _ConfigurablePlugin("p", {"oscillator.chronos"}, maker=maker)
    lp = load_plugins(
        {"plugins": {"enabled": ["p"], "p": {"x": 1}}, "oscillator": {"enabled": True}},
        known_modules=["chronos"],
        entry_points=_eps(FakeEP("p", lambda: p)),
    )
    assert lp.oscillator_for("chronos", {"d": 2}) is expected
    assert p.make_calls == 1


def test_oscillator_for_missing_method_raises():
    class P:
        def seams(self, config):
            return frozenset({"oscillator.chronos"})

        def injections(self, module, config):
            return {}

    lp = load_plugins(
        {"plugins": {"enabled": ["p"]}, "oscillator": {"enabled": True}},
        known_modules=["chronos"],
        entry_points=_eps(FakeEP("p", P)),
    )
    with pytest.raises(PluginError, match="make_oscillator"):
        lp.oscillator_for("chronos", {})


def test_oscillator_for_none_return_raises():
    p = _ConfigurablePlugin("p", {"oscillator.chronos"}, maker=lambda *_: None)
    lp = load_plugins(
        {"plugins": {"enabled": ["p"]}, "oscillator": {"enabled": True}},
        known_modules=["chronos"],
        entry_points=_eps(FakeEP("p", lambda: p)),
    )
    with pytest.raises(PluginError, match="returned None"):
        lp.oscillator_for("chronos", {})


def test_oscillator_for_undeclared_module_returns_none():
    p = _ConfigurablePlugin("p", {"chronos.network"})
    lp = load_plugins(
        {"plugins": {"enabled": ["p"]}, "oscillator": {"enabled": True}},
        known_modules=["chronos"],
        entry_points=_eps(FakeEP("p", lambda: p)),
    )
    assert lp.oscillator_for("chronos", {}) is None
    assert p.make_calls == 0


def test_manifest_entry_lists_metadata_and_sorted_seams():
    p1 = _ConfigurablePlugin("p1", {"soma.forward_model", "chronos.network"})
    p2 = _ConfigurablePlugin("p2", {"nous.engine"})
    lp = load_plugins(
        {"plugins": {"enabled": ["p1", "p2"]}},
        known_modules=["chronos", "soma", "nous"],
        entry_points=_eps(
            FakeEP("p1", lambda: p1, FakeDist("dist-one", "1.2.3")),
            FakeEP("p2", lambda: p2, FakeDist("dist-two", "4.5.6")),
        ),
    )
    assert lp.manifest_entry() == {
        "p1": {
            "distribution": "dist-one",
            "version": "1.2.3",
            "seams": ["chronos.network", "soma.forward_model"],
        },
        "p2": {
            "distribution": "dist-two",
            "version": "4.5.6",
            "seams": ["nous.engine"],
        },
    }
    assert bool(lp) is True


def test_manifest_entry_empty_when_no_plugins():
    lp = load_plugins({}, known_modules=["chronos"], entry_points=_eps())
    assert lp.manifest_entry() == {}
    assert bool(lp) is False


def test_plugin_receives_its_own_config_table():
    p = _ConfigurablePlugin("p", {"chronos.network"})
    load_plugins(
        {"plugins": {"enabled": ["p"], "p": {"alpha": 1}}},
        known_modules=["chronos"],
        entry_points=_eps(FakeEP("p", lambda: p)),
    )
    assert p.seen_config == {"alpha": 1}


def test_non_dict_plugin_table_raises():
    p = _ConfigurablePlugin("p", {"chronos.network"})
    with pytest.raises(PluginError, match="p"):
        load_plugins(
            {"plugins": {"enabled": ["p"], "p": "not-a-table"}},
            known_modules=["chronos"],
            entry_points=_eps(FakeEP("p", lambda: p)),
        )


def test_validate_plugins_enabled_not_list():
    with pytest.raises(ConfigShapeError, match=r"plugins\.enabled"):
        validate_config_shape({"plugins": {"enabled": "cl"}})


def test_validate_plugins_not_table():
    with pytest.raises(ConfigShapeError, match=r"^plugins "):
        validate_config_shape({"plugins": []})


def test_validate_plugin_table_not_table():
    with pytest.raises(ConfigShapeError, match=r"plugins\.foo"):
        validate_config_shape({"plugins": {"enabled": ["foo"], "foo": "bad"}})


def test_validate_plugins_valid():
    validate_config_shape(
        {"plugins": {"enabled": ["a", "b"], "a": {}, "b": {"x": 1}}}
    )


def test_run_context_carries_plugins():
    ctx = mint_run_context(
        seed=3,
        started_at="now",
        config={},
        model_ids={},
        version="0",
        plugins={"pl": {"distribution": "d", "version": "1", "seams": []}},
    )
    assert ctx.plugins == {
        "pl": {"distribution": "d", "version": "1", "seams": []}
    }
    assert ctx.to_dict()["plugins"] == ctx.plugins

    default = mint_run_context(
        seed=3, started_at="now", config={}, model_ids={}, version="0"
    )
    assert default.plugins == {}

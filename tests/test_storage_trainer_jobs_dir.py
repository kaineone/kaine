# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>


from kaine.storage import DEFAULT_TRAINER_JOBS_DIR, trainer_jobs_dir


def test_env_wins_over_config(monkeypatch):
    monkeypatch.setenv("KAINE_TRAINER_JOBS_DIR", "/trainer-jobs")
    config = {"sleep": {"voice_alignment": {"trainer_jobs_dir": "cfg/jobs"}}}
    assert trainer_jobs_dir(config) == "/trainer-jobs"


def test_blank_env_falls_back_to_config(monkeypatch):
    monkeypatch.setenv("KAINE_TRAINER_JOBS_DIR", "   ")
    config = {"sleep": {"voice_alignment": {"trainer_jobs_dir": "cfg/jobs"}}}
    assert trainer_jobs_dir(config) == "cfg/jobs"


def test_config_wins_over_default():
    config = {"sleep": {"voice_alignment": {"trainer_jobs_dir": "cfg/jobs"}}}
    assert trainer_jobs_dir(config) == "cfg/jobs"


def test_missing_tables_give_default():
    assert trainer_jobs_dir({}) == DEFAULT_TRAINER_JOBS_DIR
    assert trainer_jobs_dir({"sleep": {}}) == DEFAULT_TRAINER_JOBS_DIR
    assert trainer_jobs_dir({"sleep": {"voice_alignment": {}}}) == DEFAULT_TRAINER_JOBS_DIR


def test_non_dict_sleep_table_gives_default():
    assert trainer_jobs_dir({"sleep": "not-a-dict"}) == DEFAULT_TRAINER_JOBS_DIR


def test_sleep_factory_honours_the_environment(monkeypatch):
    # The sleep module resolves its jobs directory through the shared resolver,
    # so the container's KAINE_TRAINER_JOBS_DIR wins over the configured value.
    from kaine.boot.factories.sleep import voice_alignment_config_from_section

    monkeypatch.setenv("KAINE_TRAINER_JOBS_DIR", "/trainer-jobs")
    section = {
        "enabled": True,
        "base_model_path": "/models/base.gguf",
        "capability_probe_path": "/probes/capability.json",
        "abliteration_probe_path": "/probes/abliteration.json",
        "hot_swap_mode": "organ_adapter",
        "trainer_backend": "job_queue",
        "trainer_jobs_dir": "state/sleep/voice_align_jobs",
    }
    cfg = voice_alignment_config_from_section(section, {})
    assert cfg is not None
    assert cfg.trainer_jobs_dir == "/trainer-jobs"

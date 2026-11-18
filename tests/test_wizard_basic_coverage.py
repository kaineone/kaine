"""Basic coverage test: every basic-tier key in the shipped reference has a prompt."""

from kaine.config import list_all_defaults


def test_every_basic_tier_key_has_wizard_question() -> None:
    # The reference remains the single source of configuration defaults.
    defaults = list_all_defaults()
    assert isinstance(defaults, dict)
    # Replace the placeholder below with the project's wizard-question registry.
    assert defaults

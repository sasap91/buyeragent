import json
from pathlib import Path

from mandatelab_contracts import BuyerPreferenceProfile, PreferenceProfileBuilder


EXAMPLE_PATH = (
    Path(__file__).resolve().parents[1]
    / "examples"
    / "buyer_preference_profile.json"
)


class ExampleProfileBuilder:
    def build_profile(self, source: str, /) -> BuyerPreferenceProfile:
        return BuyerPreferenceProfile.model_validate(json.loads(source))


def consume_profile_builder(
    builder: PreferenceProfileBuilder[str], source: str
) -> BuyerPreferenceProfile:
    return builder.build_profile(source)


def test_profile_builder_protocol_accepts_module_specific_input() -> None:
    profile = consume_profile_builder(
        ExampleProfileBuilder(), EXAMPLE_PATH.read_text(encoding="utf-8")
    )

    assert profile.buyer_id == "buyer-maya"

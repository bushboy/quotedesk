"""The release set, the customer voice, and the live-number rule. No live model."""

from pathlib import Path

import pytest
import yaml

from eval.customer import CustomerPrompt, ScriptedCustomer
from eval.release import live_number_allowed
from eval.run_gate import BUSINESSES, GATE, run
from quotedesk.adapters.outbound.persistence.tenants import CATALOGUE, known_tenant
from quotedesk.infrastructure.config import SettingsError, get_settings

ROOT = Path(__file__).resolve().parents[2]
DOORS = ROOT / "eval" / "conversations" / "oakmere.yaml"


def test_each_served_business_has_a_release_set():
    for slug in BUSINESSES:
        document = yaml.safe_load((GATE / f"{slug}.yaml").read_text(encoding="utf-8"))
        count = len(document["conversations"])
        assert 20 <= count <= 30
        for item in document["conversations"]:
            assert item["expected_outcome"]
            assert "rule_id" in item
            assert "required_facts" in item
            assert item["forbidden"] is not None
            assert item["persona"]


def test_the_persona_changes_the_wording_and_not_the_facts():
    voice = ScriptedCustomer()
    facts = (("size_litres", "5000"), ("existing_level_base", "true"))
    persona = "knows the size and that the base is level"
    first = voice.complete(CustomerPrompt(persona=persona, seed=0, facts=facts, turn=1)).text
    second = voice.complete(CustomerPrompt(persona=persona, seed=1, facts=facts, turn=1)).text
    assert first != second
    for sentence in (first, second):
        assert "5000" in sentence
        assert "true" in sentence
        assert "knows the size" in sentence


def test_a_business_without_three_passes_has_no_live_number():
    assert live_number_allowed([]) is False
    assert live_number_allowed([True, True]) is False
    assert live_number_allowed([True, True, False]) is False
    assert live_number_allowed([False, True, True, True]) is True
    for profile in CATALOGUE:
        assert profile.phone_number_id == ""
    doors = yaml.safe_load(DOORS.read_text(encoding="utf-8"))
    assert doors["served"] is False
    assert live_number_allowed([]) is False


def test_oakmere_is_written_before_it_is_served():
    text = DOORS.read_text(encoding="utf-8")
    document = yaml.safe_load(text)
    assert document["served"] is False
    assert document["prices"] == []
    assert 20 <= len(document["conversations"]) <= 30
    situations = "\n".join(item["situation"] for item in document["conversations"])
    assert "R " not in situations
    assert "oakmere" not in {profile.slug for profile in CATALOGUE}
    with pytest.raises(ValueError, match="aquasure or frameworks"):
        known_tenant("oakmere")


def test_oakmere_is_not_a_tenant(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://quotedesk:quotedesk@127.0.0.1:1/quotedesk")
    monkeypatch.setenv("MODEL", "script")
    monkeypatch.setenv("TENANT", "oakmere")
    with pytest.raises(SettingsError, match="aquasure or frameworks"):
        get_settings()


def test_the_release_set_meets_the_targets():
    report = run(seed=0)
    assert set(report["businesses"]) == set(BUSINESSES)
    for slug, numbers in report["businesses"].items():
        assert 20 <= numbers["conversations"] <= 30
        assert numbers["silent"] == 0
        assert numbers["unfounded"] == 0
        assert numbers["outcome_accuracy"] == 1
        assert numbers["passed"] is True
        assert numbers["cost_per_conversation"] == 0
    missed = [
        f"{row['id']} outcome={row['outcome']} rule={row['rule_id'] or 'none'} "
        f"forbidden={row['forbidden']} unfounded={row['unfounded']} reply={row['reply'][:140]!r}"
        for row in report["rows"]
        if row["silent"] or row["forbidden"] or row["unfounded"] or not row["outcome_match"] or not row["rule_match"]
    ]
    assert missed == []

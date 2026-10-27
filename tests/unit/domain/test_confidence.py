from decimal import Decimal

from quotedesk.domain.services.confidence import (
    ConfidenceBand,
    ConfidenceChecks,
    MediaUsability,
    RecordedMask,
    SizeFact,
    SizeSource,
    cross_model_agreement,
    derive_confidence,
    measurement_acceptable,
    media_is_usable,
    rate_card_match,
    required_fields_complete,
)

THRESHOLD = Decimal("0.80")


def _checks(**overrides: bool) -> ConfidenceChecks:
    fields = {
        "required_fields": True,
        "agreement": True,
        "measurement": True,
        "media_usable": True,
        "rate_card": True,
    }
    fields.update(overrides)
    return ConfidenceChecks(**fields)


def test_confidence_all_five_pass_is_high():
    assert derive_confidence(_checks()) == ConfidenceBand.HIGH


def test_confidence_one_non_rate_failure_is_medium():
    for name in ("required_fields", "agreement", "measurement", "media_usable"):
        assert derive_confidence(_checks(**{name: False})) == ConfidenceBand.MEDIUM


def test_confidence_rate_card_miss_alone_is_low():
    assert rate_card_match(("TANK-UNKNOWN",), {"TANK-5000"}) is False
    assert derive_confidence(_checks(rate_card=False)) == ConfidenceBand.LOW


def test_confidence_two_failures_are_low():
    pairs = (
        {"required_fields": False, "media_usable": False},
        {"agreement": False, "measurement": False},
        {"rate_card": False, "required_fields": False},
    )
    for overrides in pairs:
        assert derive_confidence(_checks(**overrides)) == ConfidenceBand.LOW


def test_confidence_all_five_fail_is_low():
    band = derive_confidence(
        ConfidenceChecks(
            required_fields=False,
            agreement=False,
            measurement=False,
            media_usable=False,
            rate_card=False,
        )
    )
    assert band == ConfidenceBand.LOW


def test_confidence_text_only_agreement_passes():
    assert (
        cross_model_agreement(
            has_image=False,
            has_video=False,
            spark_objects=(),
            sam_error=False,
            masks=(),
            threshold=THRESHOLD,
        )
        is True
    )


def test_confidence_sam_error_fails_agreement():
    cases = (
        {"sam_error": True, "masks": ()},
        {"sam_error": False, "masks": ()},
        {
            "sam_error": False,
            "masks": (RecordedMask(label="tank", score=Decimal("0.79")),),
        },
    )
    for case in cases:
        assert (
            cross_model_agreement(
                has_image=True,
                has_video=False,
                spark_objects=("tank",),
                threshold=THRESHOLD,
                **case,
            )
            is False
        )


def test_confidence_photo_only_size_fails_measurement():
    assert (
        measurement_acceptable((SizeFact(litres=5000, source=SizeSource.PHOTO_INFERRED),))
        is False
    )
    assert (
        measurement_acceptable((SizeFact(litres=5000, source=SizeSource.CUSTOMER_STATED),))
        is True
    )
    assert (
        measurement_acceptable((SizeFact(litres=5000, source=SizeSource.REFERENCE_OBJECT),))
        is True
    )


def test_confidence_disagreement_fails_measurement():
    sizes = (
        SizeFact(litres=5000, source=SizeSource.CUSTOMER_STATED),
        SizeFact(litres=2500, source=SizeSource.PHOTO_INFERRED),
    )
    assert measurement_acceptable(sizes) is False


def test_confidence_blank_required_field_is_incomplete():
    assert required_fields_complete({"size": ""}, ("size",)) is False
    assert required_fields_complete({"size": " "}, ("size",)) is False
    assert required_fields_complete({}, ("size",)) is False
    assert required_fields_complete({"size": "5000"}, ("size",)) is True


def test_confidence_unusable_media():
    for flag in ("blur", "darkness", "unintelligible_audio", "wrong_subject"):
        media = MediaUsability(has_media=True, **{flag: True})
        assert media_is_usable(media) is False
    assert media_is_usable(MediaUsability(has_media=True)) is True
    assert media_is_usable(MediaUsability(has_media=False)) is True

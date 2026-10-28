import json
from pathlib import Path

from quotedesk.adapters.outbound.models.baseten.sam_parser import SamFailure, parse_sam_response
from quotedesk.application.dto.agent import ExtractionResult
from quotedesk.domain.services.confidence import RecordedMask

_ROOT = Path(__file__).resolve().parents[4]
_EXTRACTION = _ROOT / "tests" / "fixtures" / "extraction"
_SAM = _ROOT / "tests" / "fixtures" / "sam"


def load_recording(name: str) -> ExtractionResult:
    payload = json.loads((_EXTRACTION / f"{name}.json").read_text(encoding="utf-8"))
    parsed = parse_sam_response(json.loads((_SAM / payload["sam"]).read_text(encoding="utf-8")))
    flags = {
        "summary": str(payload["summary"]),
        "objects": tuple(str(name) for name in payload["objects"]),
        "blur": bool(payload["blur"]),
        "darkness": bool(payload["darkness"]),
        "wrong_subject": bool(payload["wrong_subject"]),
    }
    if isinstance(parsed, SamFailure):
        return ExtractionResult(sam_error=True, sam_sentence=parsed.sentence, **flags)
    return ExtractionResult(
        masks=tuple(RecordedMask(label=mask.label, score=mask.score) for mask in parsed.masks),
        **flags,
    )


class RecordedEnricher:
    """The tank photo's recording. This slice does not call a model."""

    def for_image(self, provider_message_id: str) -> ExtractionResult:
        return load_recording("tank-on-base")

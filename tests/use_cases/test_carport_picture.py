"""A carport picture follows a confirmed FrameWorks quote. The renderer is a fake."""

from pathlib import Path
import re
from uuid import uuid4

from quotedesk.adapters.outbound.parsers.aquasure import load_playbook
from quotedesk.application.dto.agent import BusinessView, ExtractionResult, ModelReply
from quotedesk.application.dto.inbound import InboundMessage
from quotedesk.application.dto.published import PublishedPolicy
from quotedesk.application.dto.tenant import TenantContext
from quotedesk.application.use_cases.conversation.carport_sketch import FAILED, CarportSketch, drawing_prompt
from quotedesk.domain.case.case_file import CaseFile
from quotedesk.domain.conversation.events import Conversation
from quotedesk.domain.policy.clauses import ClausePolicy
from quotedesk.domain.services.price import RateCard, RateCardItem
from quotedesk.domain.shared.money import Money
from quotedesk.infrastructure.config import Settings
from quotedesk.infrastructure.main import create_app
from tests.unit.domain.fabricator_policy import fabricator_policy
from tests.use_cases.test_typed_turn import (
    CONTEXT,
    CONVERSATION,
    TANK,
    TENANT,
    WA,
    Cases,
    Conversations,
    QuoteScript,
    _record_sheet,
    _sheet_policies,
    at,
    harness,
    say,
)

_URL = "postgresql://quotedesk:quotedesk@127.0.0.1:1/quotedesk"
_PLAYBOOK = Path(__file__).resolve().parents[2] / "seeds" / "frameworks.yaml"
_ECO = (
    "We can send a fixed quote for this sheeting. The total is R 297500.00. "
    "Economy sheeting R 297500.00. /card/QD-1042?code=1042"
)
_TOTAL = "We can send a fixed quote for this sheeting. The total is R 5075.00."


class Drawer:
    def __init__(self, error: BaseException | None = None) -> None:
        self.requests = []
        self.error = error

    def draw(self, request):
        self.requests.append(request)
        if self.error is not None:
            raise self.error
        return b"\x89PNG"


class Host:
    def __init__(self, photos: dict[str, bytes] | None = None) -> None:
        self.photos = photos or {}

    def get(self, media_id: str):
        data = self.photos.get(media_id)
        if data is None:
            return None
        return ("image/jpeg", data)


class PictureSender:
    def __init__(self) -> None:
        self.sent: list[tuple[str, str]] = []
        self.images: list[str | None] = []

    def send(self, wa_id: str, body: str, *, buttons=(), image_url=None) -> None:
        self.sent.append((wa_id, body))
        self.images.append(image_url)


def _playbook():
    return load_playbook(_PLAYBOOK)


def _case(*rows: tuple[str, str], confirmed: bool = True) -> CaseFile:
    event = uuid4()
    case = CaseFile.open(CONVERSATION, TENANT).add_job("carport", "carport")
    facts = {"item_codes": "SHADE-NET", "width_m": "5", "length_m": "7", "existing_frame": "true"}
    facts.update(dict(rows))
    for key, value in facts.items():
        case = case.record_fact("carport", uuid4(), key, value, "customer_text", event)
    if confirmed:
        case = case.confirm_spec("carport", uuid4(), event)
    return case


def _sketch(case: CaseFile, drawer: Drawer, host: Host | None = None, trade: str = "carports and sheeting"):
    conversations = Conversations()
    return CarportSketch(drawer, Cases(case), conversations, _sheet_policies(), host or Host(), trade), conversations


def _image(conversations: Conversations, body: str, media_id: str, message_id: str) -> None:
    current = conversations.get(TENANT, CONVERSATION) or Conversation.open(CONVERSATION)
    conversations.save(TENANT, current.append(message_id, at(0), body).conversation)
    conversations.remember(
        TENANT,
        InboundMessage(
            conversation_id=CONVERSATION,
            provider_message_id=message_id,
            wa_id=WA,
            at=at(0),
            kind="image",
            body=body,
            media_id=media_id,
            mime="image/jpeg",
        ),
    )


def _draw(sketch: CarportSketch, body: str = _TOTAL):
    return sketch.after_quote(CONTEXT, CONVERSATION, body)


def test_shade_net_sags_and_the_solid_sheets_do_not():
    options = {option.value: option for option in _options(_playbook())}
    assert options["SHADE-NET"].sags is True
    assert options["SHEET-ECO"].sags is False
    assert options["SHEET-COLOUR"].sags is False
    assert options["SHEET-INSUL"].sags is False
    assert options["SHEET-POLY"].sags is False


def test_a_sagging_sheet_asks_for_a_curve_and_a_solid_sheet_stays_straight():
    curved = drawing_prompt(label="Shade net, 80%", width="5", length="7", curved=True, finish="", gutter=False, onto_photo=False)
    straight = drawing_prompt(
        label="Galvanised IBR sheeting",
        width="5",
        length="7",
        curved=False,
        finish="Painted",
        gutter=True,
        onto_photo=True,
    )
    assert "sags in a curve" in curved
    assert "straight pitched" not in curved
    assert "straight pitched roof of Galvanised IBR sheeting" in straight
    assert "The frame is Painted." in straight
    assert "A gutter runs along the front." in straight
    assert "Keep this garage and this wall." in straight
    for prompt in (curved, straight):
        assert "5" in prompt and "7" in prompt
        assert re.search(r"\bR \d", prompt) is None
        assert "rand" not in prompt.casefold()
        assert "FrameWorks" not in prompt
        assert "AquaSure" not in prompt


def test_a_confirmed_shade_net_with_a_garage_photo_asks_for_an_edit():
    drawer = Drawer()
    sketch, conversations = _sketch(_case(), drawer, Host({"garage": b"garage-bytes"}))
    _image(conversations, "The garage wall.", "garage", "img-garage")
    drawn = _draw(sketch)
    assert drawn is not None and drawn.image_url
    request = drawer.requests[0]
    assert request.photo == b"garage-bytes"
    assert "sags in a curve" in request.prompt
    assert "Shade net, 80%" in request.prompt
    assert "plain plastered wall" not in request.prompt
    assert drawn.caption == "This is a drawing of that spec on your photo, not a measure."


def test_the_latest_garage_photo_is_the_one_that_is_edited():
    drawer = Drawer()
    sketch, conversations = _sketch(_case(), drawer, Host({"older": b"older", "newer": b"newer"}))
    _image(conversations, "The house.", "older", "img-old")
    _image(conversations, "A dog.", "dog", "img-dog")
    _image(conversations, "The garage.", "newer", "img-new")
    _draw(sketch)
    assert drawer.requests[0].photo == b"newer"


def test_a_read_that_names_a_garage_is_enough():
    drawer = Drawer()
    sketch, conversations = _sketch(_case(), drawer, Host({"shot": b"from-the-read"}))
    _image(conversations, "", "shot", "img-read")
    conversations.enrichment = lambda _tenant, message_id: ExtractionResult(
        summary="a garage door",
        objects=("garage door",),
    )
    _draw(sketch)
    assert drawer.requests[0].photo == b"from-the-read"


def test_a_solid_sheet_with_no_photo_asks_for_a_straight_generation():
    drawer = Drawer()
    sketch, _conversations = _sketch(_case(("item_codes", "SHEET-ECO")), drawer)
    drawn = _draw(sketch)
    assert drawn is not None
    request = drawer.requests[0]
    assert request.photo is None
    assert "straight pitched roof of Galvanised IBR sheeting" in request.prompt
    assert "plain plastered wall" in request.prompt
    assert drawn.caption == "This is a drawing of that spec against a plain wall and garage, not a measure."


def test_a_blurry_photo_asks_for_a_generation_and_says_so():
    drawer = Drawer()
    sketch, conversations = _sketch(
        _case(("media_usable", "false")),
        drawer,
        Host({"garage": b"garage-bytes"}),
    )
    _image(conversations, "The garage.", "garage", "img-blur")
    drawn = _draw(sketch)
    assert drawn is not None
    assert drawer.requests[0].photo is None
    assert "plain plastered wall" in drawer.requests[0].prompt
    assert drawn.caption.startswith("That photo was hard to use.")


def test_a_failed_drawing_returns_no_picture():
    drawer = Drawer(error=RuntimeError("down"))
    sketch, _conversations = _sketch(_case(), drawer)
    drawn = _draw(sketch)
    assert drawn is not None
    assert drawn.caption == FAILED
    assert drawn.image_url is None


def test_a_range_an_escalation_and_a_site_measure_draw_nothing():
    drawer = Drawer()
    sketch, _conversations = _sketch(_case(), drawer)
    for body in (
        "The indicative range is R 12600.00.",
        "I'll ask someone from the business to pick this up.",
        "This one needs a site measure before we can give you a price. The visit fee is R 750.",
    ):
        assert _draw(sketch, body) is None
    assert drawer.requests == []


def test_an_unconfirmed_spec_draws_nothing():
    drawer = Drawer()
    sketch, _conversations = _sketch(_case(confirmed=False), drawer)
    assert _draw(sketch) is None
    assert drawer.requests == []


def test_aquasure_never_calls_the_renderer():
    drawer = Drawer()
    sketch, _conversations = _sketch(_case(), drawer, trade="water tanks and pumps")
    assert _draw(sketch) is None
    assert drawer.requests == []


def test_a_known_gutter_and_finish_are_named():
    drawer = Drawer()
    sketch, _conversations = _sketch(_case(("gutters", "true"), ("finish", "painted")), drawer)
    _draw(sketch)
    prompt = drawer.requests[0].prompt
    assert "A gutter runs along the front." in prompt
    assert "The frame is Painted." in prompt
    assert re.search(r"\bR \d", prompt) is None


def _options(playbook):
    for job in playbook.job_types:
        for fact in job.facts:
            if fact.key == "sheet":
                return fact.options
    return ()


def _shade_policies():
    card = RateCard(
        vat_inclusive=True,
        site_visit_fee=Money("750.00"),
        items=(
            RateCardItem(item_code="SHADE-NET", description="Shade net", unit_price=Money("145.00"), unit="per m²"),
            RateCardItem(item_code="SHEET-ECO", description="Economy sheeting", unit_price=Money("8500.00"), unit="per m²"),
        ),
    )
    bundle = PublishedPolicy(
        policy=fabricator_policy(),
        rate_card=card,
        clause_policy=ClausePolicy(
            templates=(),
            settings={"deposit_percent": 30, "validity_days": 14},
            rate_card_codes=("SHADE-NET", "SHEET-ECO"),
        ),
        playbook=_playbook(),
    )

    class Sheets:
        def published(self, tenant_id):
            return bundle

    return Sheets()


class _Record:
    def __init__(self, sheet: str) -> None:
        self.sheet = sheet

    def complete(self, prompt):
        if prompt.tool_payloads:
            return ModelReply(text="", tool_calls=())
        fact = {"source": "customer_text", "event_id": prompt.messages[-1].provider_message_id}
        return _record_sheet(
            [
                {"key": "item_codes", "value": self.sheet, **fact},
                {"key": "width_m", "value": "5", **fact},
                {"key": "length_m", "value": "7", **fact},
                {"key": "existing_frame", "value": "true", **fact},
            ],
        )


def _quote(sheet: str, policies, attach):
    business = BusinessView(name="FrameWorks", trade="carports and sheeting")
    conversations, cases, _sender, _clock, turn = harness(_Record(sheet), business=business, policies=policies)
    box = PictureSender()
    turn._sender = box
    drawer = Drawer()
    if attach is not None:
        turn._pictures = attach(drawer, cases, conversations, policies)
    say(conversations, "Sheeting for the 5 by 7 carport.", 0, str(uuid4()))
    turn.execute(CONTEXT, CONVERSATION)
    say(conversations, "Yes", 0, str(uuid4()))
    turn.execute(CONTEXT, CONVERSATION)
    return box, drawer, conversations


def _attached(drawer, cases, conversations, policies, host=None, trade="carports and sheeting"):
    return CarportSketch(drawer, cases, conversations, policies, host or Host(), trade)


def test_a_shade_net_quote_with_the_photo_already_on_the_case_draws_it():
    policies = _shade_policies()
    business = BusinessView(name="FrameWorks", trade="carports and sheeting")
    conversations, cases, _sender, _clock, turn = harness(_Record("SHADE-NET"), business=business, policies=policies)
    box = PictureSender()
    turn._sender = box
    drawer = Drawer()
    turn._pictures = _attached(drawer, cases, conversations, policies, Host({"garage": b"garage-bytes"}))
    _image(conversations, "The garage wall.", "garage", "img-garage")
    say(conversations, "Shade net for the 5 by 7 carport.", 0, str(uuid4()))
    turn.execute(CONTEXT, CONVERSATION)
    say(conversations, "Yes", 0, str(uuid4()))
    turn.execute(CONTEXT, CONVERSATION)
    plain, _untouched, _ignored = _quote("SHADE-NET", policies, None)
    assert box.sent[1] == plain.sent[1]
    assert "The total is" in box.sent[1][1]
    assert box.sent[2][1] == "This is a drawing of that spec on your photo, not a measure."
    assert box.images[2] and box.images[2].startswith("data:image/png;base64,")
    assert drawer.requests[0].photo == b"garage-bytes"
    assert "sags in a curve" in drawer.requests[0].prompt


def test_an_ibr_quote_with_no_photo_asks_for_a_straight_roof():
    policies = _shade_policies()
    box, drawer, _conversations = _quote("SHEET-ECO", policies, _attached)
    assert "straight pitched roof of Galvanised IBR sheeting" in drawer.requests[0].prompt
    assert drawer.requests[0].photo is None
    assert box.sent[2][1] == "This is a drawing of that spec against a plain wall and garage, not a measure."
    assert "The total is R 297500.00" in box.sent[1][1]


def test_a_blurry_garage_photo_on_a_quote_says_the_photo_was_hard_to_use():
    policies = _shade_policies()
    business = BusinessView(name="FrameWorks", trade="carports and sheeting")
    conversations, cases, _sender, _clock, turn = harness(_Record("SHEET-ECO"), business=business, policies=policies)
    box = PictureSender()
    turn._sender = box
    drawer = Drawer()
    turn._pictures = _attached(drawer, cases, conversations, policies, Host({"garage": b"garage-bytes"}))
    turn.enricher = type("Blur", (), {"for_image": lambda self, message_id: ExtractionResult(summary="a garage", objects=("garage",), blur=True)})()
    _image(conversations, "The garage.", "garage", "img-blur")
    say(conversations, "Economy sheeting for the 5 by 7 carport.", 0, str(uuid4()))
    turn.execute(CONTEXT, CONVERSATION)
    say(conversations, "Yes", 0, str(uuid4()))
    turn.execute(CONTEXT, CONVERSATION)
    assert drawer.requests[0].photo is None
    assert box.sent[2][1].startswith("That photo was hard to use.")
    assert "The total is R 297500.00" in box.sent[1][1]
    assert box.images[2] and box.images[1] is None


def test_a_renderer_failure_still_sends_the_quote_and_no_picture():
    policies = _shade_policies()

    def attach(drawer, cases, conversations, policies):
        drawer.error = RuntimeError("down")
        return _attached(drawer, cases, conversations, policies)

    box, drawer, _conversations = _quote("SHEET-ECO", policies, attach)
    assert box.sent[1][1] == _ECO
    assert box.sent[2] == (WA, FAILED)
    assert box.images[2] is None
    assert drawer.requests


def test_aquasure_sends_the_quote_and_no_picture():
    drawer = Drawer()
    conversations, cases, sender, _clock, turn = harness(QuoteScript("The total is R 3 000."))
    turn._pictures = CarportSketch(drawer, cases, conversations, _sheet_policies(), Host(), "water tanks and pumps")
    say(conversations, TANK, 0, str(uuid4()))
    turn.execute(TenantContext(tenant_id=TENANT), CONVERSATION)
    assert len(sender.sent) == 1
    assert "The total is R 5550.00" in sender.sent[0][1]
    assert drawer.requests == []


def test_with_the_switch_off_a_frameworks_quote_is_unchanged():
    conversations, _cases, sender, _clock, turn = harness(
        _Record("SHEET-ECO"),
        business=BusinessView(name="FrameWorks", trade="carports and sheeting"),
        policies=_sheet_policies(),
    )
    assert turn._pictures is None
    say(conversations, "Economy sheeting for the 5 by 7 carport.", 0, str(uuid4()))
    turn.execute(CONTEXT, CONVERSATION)
    say(conversations, "Yes", 0, str(uuid4()))
    turn.execute(CONTEXT, CONVERSATION)
    assert sender.sent[1] == (WA, _ECO)
    assert len(sender.sent) == 2


def test_the_switch_builds_a_renderer_only_for_frameworks_when_it_is_on():
    off = create_app(Settings(database_url=_URL, tenant="frameworks", model="script", store="memory"))
    assert off.state.turn._pictures is None
    no_key = create_app(
        Settings(database_url=_URL, tenant="frameworks", model="script", store="memory", carport_picture=True),
    )
    assert no_key.state.turn._pictures is None
    aqua = create_app(
        Settings(
            database_url=_URL,
            tenant="aquasure",
            model="script",
            store="memory",
            carport_picture=True,
            meta_api_key="test-key",
        ),
    )
    assert aqua.state.turn._pictures is None
    works = create_app(
        Settings(
            database_url=_URL,
            tenant="frameworks",
            model="script",
            store="memory",
            carport_picture=True,
            meta_api_key="test-key",
        ),
    )
    assert works.state.turn._pictures is not None


def test_quote_files_do_not_name_the_model_or_the_switch():
    root = Path(__file__).resolve().parents[2]
    for name in (
        "quotedesk/application/use_cases/conversation/run_agent_turn.py",
        "quotedesk/application/use_cases/tools/get_quote.py",
        "quotedesk/domain/services/plan.py",
        "quotedesk/application/prompts.py",
    ):
        text = (root / name).read_text(encoding="utf-8")
        assert "muse-image" not in text
        assert "carport_picture" not in text

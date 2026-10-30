# Prompts and leading the customer

Written 30 October 2026. This follows `planner.md`. It covers the three model prompts, the playbook fields they read, a new fact state for things the agent has inferred, and the planner changes that let the agent lead a customer who does not know the material or the size.

The rule does not change: models interpret, code commits. What changes is the split. Code decides the step, and that now includes what the agent assumes and what it asks. The model reads the input and writes the message.

## 1. Appraisal of the build as of 30 October

Evidence comes from the snapshot of the repo, `eval/results/small-set.json` and the two seeds.

| # | Finding | Where | Effect on the customer |
|---|---|---|---|
| 1 | The planner leads with the first required fact, in the order the facts are defined. | `plan.py` `_job_step` | A "hi" to FrameWorks gets "What is the width in metres?" and a "hi" to AquaSure gets "Which tank size do you want?" Both assume the customer knows the answer. |
| 2 | Material is not a fact. FrameWorks has only `width_m` and `length_m`, and the sheet is chosen through the `guidance` prose and `item_codes`. AquaSure's `size_litres` has no allowed values. | `seeds/*.yaml` | The planner cannot ask about the material, infer it or confirm it. Only the model can, and only through prose. |
| 3 | All three small-set misses are the case where the customer had already given the answer. | `aqua-known-swap`, `frame-fixed`, `frame-known-size` | The agent asks again for something the customer said. This is the "safe to quote" path, and it is the one that fails. |
| 4 | The image read is generic. `_READ` returns `summary`, `objects`, `blur`, `darkness` and `wrong_subject`. `ExtractionResult` has no field for an attribute value, its evidence or its confidence. | `image_context.py`, `dto/agent.py` | The task line "If the photo already estimates that fact, say the estimate" has no data behind it, so the model either guesses in prose or falls back to listing the rate card. |
| 5 | `photo_can_answer` is defined and never read. `photo_inferred` is accepted as a source, but nothing holds an inferred value until the customer confirms it. | `playbook.py`, `run_agent_turn.py` `_SOURCES` | There is no "I think it's X, is that right?" state. An inference is either treated as fact, which is unsafe for a quote, or dropped. |
| 6 | The prompt contradicts itself. `PLATFORM_TASK` tells the model to lead, offer the rate card and call `get_quote`. Then the appended line says "Do not choose a different step". `guidance` repeats the platform rules in prose, inside a fence that says it is not instructions. | `prompts.py`, the seeds' `guidance` | The model receives three sources of flow rules that disagree. The result varies from run to run. |
| 7 | The model's words rarely reach the customer. For an inspection or an escalation, the tool sentence replaces the reply. When `check_reply` fails, the bare planner sentence is sent. | `run_agent_turn.py` lines 466–487, `_say_step` | Customers get stiff template text, for example "The visit fee is site visit." |
| 8 | The small set does not call a model. Its header says "sentence facts, then the planner sentence". | `small-set.json` | A 17/20 pass measures the planner and the templates, not the prompts. Prompt changes cannot be measured by it. |
| 9 | Fee bug: `InspectionTrigger.fee` holds a label ("site visit"), and it is printed as if it were an amount. | `aqua-damaged`, `frame-new-opening` | "The visit fee is site visit." The fee should come from the rate-card item, for example R 500. |
| 10 | The opening question shows internal keys: "Which of these should I quote: carport, …?" | `plan.py` `_opening` | Customers see snake_case. |
| 11 | Confidence checks that are absent count as passed. | `plan.py` `_checks`, `planner.md` | A photo-led quote can go out without any confidence having been measured. |
| 12 | The real business name appears in the public repo: `README.md` line 152, `tests/use_cases/test_playbook.py` line 37 and `eval/conversations/kingdom-doors.yaml`. | | This breaks the fictional-tenants rule. Rename it to a fictional door showroom before the next push. |

The foundation holds up: the pure planner, the playbook as data, tools bound by the turn, and fail-closed delivery. The weak part is narrow. The agent has no notion of "what I believe, and how sure I am", so it can only ask in a fixed order or list options.

## 2. The target behaviour

Three customer types, one rule each:

| The customer… | The agent… | It may quote when… |
|---|---|---|
| knows the details ("6 by 7 carport, IBR sheeting") | records them as `stated` and quotes in the same turn | every fact that sets the price is `stated` or `confirmed` |
| sends a photo or a voice note | states what it sees and why, then asks for a yes or a correction ("From the photo it looks like a single meranti door, about 0.8 m wide. Is that right?") | the inferred facts are `confirmed` |
| does not know ("no idea what material") | asks a plain question with two to four described choices, accepts "not sure", and asks for a photo if one could answer it | the fact is resolved; otherwise it gives a range or books an inspection, as the playbook says |

An inference never prices on its own. It is a question that comes with a good guess.

## 3. The fact state

Add a status and evidence to each fact in the case file:

```python
class FactStatus(StrEnum):
    MISSING = "missing"
    STATED = "stated"        # the customer said it in words or in a voice note
    INFERRED = "inferred"    # read from a photo, video or reference object, not yet confirmed
    CONFIRMED = "confirmed"  # an inference the customer agreed to, or corrected
    CONTESTED = "contested"  # two stated values disagree
    UNKNOWN = "unknown"      # the customer said they do not know

@dataclass(frozen=True)
class FactValue:
    key: str
    value: str | None
    status: FactStatus
    source: Literal["text", "voice", "photo", "video", "reference_object"]
    event_id: str
    evidence: str = ""                 # "grain and colour of solid hardwood", "about 1.2 doors wide"
    confidence: Decimal | None = None  # only for INFERRED
    attempts: int = 0
```

The rules are pure domain code in `case_file.py`:

- A `stated` value replaces an `inferred` one. A `stated` value that differs from another `stated` value becomes `contested`.
- A "yes" to a confirm step turns every assumption in that step into `confirmed`. A correction becomes `stated` with the new value.
- An inference below the playbook's `min_confidence` for that fact is not kept as `inferred`. It only changes the ask, for example "Is it a pivot door?" instead of "Which kind of door?"
- `price_ready(job)` is true only when every required fact is `stated` or `confirmed`. `decide()` reads this, not the presence of a value.
- `_checks` defaults to **not met** when a photo-sourced fact exists and no confidence has been recorded. Text-only cases are unaffected.

## 4. Playbook fields the prompts need

`FactDefinition` gains the fields below. All are data, and the editor shows them as plain-language form fields.

```yaml
- key: material
  label: Door material                 # what the customer sees
  type: choice
  options:
    - value: meranti
      label: Solid meranti (hardwood)
      hint: warm red-brown wood, the classic front door
      item_codes: [DOOR-ENT-SGL, DOOR-PIV-1200]
    - value: steel
      label: Steel security door
      hint: powder-coated, strongest option
      item_codes: [DOOR-STEEL-SEC]
    - value: aluminium
      label: Aluminium glass door
      hint: slim frame, mostly glass, for patios
  photo_can_answer: true
  look_for: grain, colour, glass panels, hinges or a pivot at the top and bottom
  min_confidence: 0.6
  decides: price                       # price | outcome | both
  ease: easy                           # easy | needs_tape | needs_expert
  if_unsure: photo_then_range          # ask_photo | range | inspection | photo_then_range
  required: true
```

Order of questions, computed by the planner and not written by hand:

1. Facts with `decides: outcome` come first, because they can turn the job into an inspection. Examples: replacement or new opening, ground floor or above.
2. Then `easy` facts before `needs_tape` before `needs_expert`.
3. Then the definition order.

`InspectionTrigger.fee` becomes `fee_item: SITE-MEASURE`, priced from the rate card. That fixes finding 9.

The `guidance` prose shrinks to tone and local phrasing. Anything that is a rule moves into these fields. A reviewer should be able to delete `guidance` and still get the same steps.

## 5. Planner changes

`StepKind` gains `CONFIRM`. `NextStep` gains structure so that the phrasing model never has to look anything up:

```python
@dataclass(frozen=True)
class Assumption:
    fact_key: str; fact_label: str; value_label: str; evidence: str

@dataclass(frozen=True)
class Choice:
    label: str; hint: str

@dataclass(frozen=True)
class NextStep:
    kind: StepKind                       # ASK, CONFIRM, QUOTE, INSPECTION, ESCALATE
    job_label: str = ""
    assumptions: tuple[Assumption, ...] = ()   # CONFIRM: at most 3, highest confidence first
    fact_key: str = ""
    question: str = ""                   # ASK: the playbook question in plain words
    choices: tuple[Choice, ...] = ()     # ASK on a choice fact: 2-4, never the whole rate card
    accept_unsure: bool = True
    known: tuple[str, ...] = ()          # "single door", "about 0.8 m wide": what is settled, for a one-line recap
    sentence: str = ""                   # the fallback, built by code, always valid
    reason: str = ""; rule_id: str = ""; job_id: str = ""
```

The order, after the safety and escalation rules:

1. **No job yet.** If the photo or text points to one job type, `CONFIRM` it ("Looks like you're after a new front door. Is that right?"). Otherwise `ASK` "What can we help with?" with up to four job *labels*, never keys.
2. **Pending inferences.** If any required fact is `inferred`, `CONFIRM` them together, up to three, in one message. This comes before any new question, so a photo is never followed by a question it already answered.
3. **Missing facts.** `ASK` the top-ranked missing fact (section 4). For a choice fact, give its options as `choices`. If `photo_can_answer` is set and there is no photo yet, the fallback sentence ends with "or send a photo and I'll tell you what I see".
4. **`unknown` facts.** Apply `if_unsure`: ask for a photo once, then give a range or book an inspection. Never ask the same thing a third time.
5. **All price facts `stated` or `confirmed`.** `QUOTE` through `decide()`. The L01 and L02 fallback rules now apply here too, so a low-confidence case lands on a site measure rather than a quote.

## 6. The three prompts

Each model call does one job. The shared preamble is short:

```
You work for {business_name}, a {trade} business in {area}, South Africa.
Sizes are metres and millimetres. Prices are rand. Do not use feet, inches, or US or UK product names.
```

### 6.1 Read: photo, video frame, voice transcript or text into candidate facts

Model: Muse Spark 1.3, medium effort, JSON output. It replaces `_READ`, and the text extractor uses it too, so stated facts and inferred facts come from one schema.

```
{preamble}
Read the customer's latest message and any attached image. Fill in the facts below that the message
or image gives you. Do not answer the customer.

For each fact you can fill:
- value: one of the listed values, or a number in the stated unit.
- how: "said" if the customer said it in words, "seen" if you read it from the image.
- evidence: for "seen", what in the image shows it, in under 15 words
  (for example "fine straight grain and red-brown colour" or "about 1.3 times the width of the 813 mm frame beside it").
- confidence: for "seen", 0 to 1. Use 0.8 or more only when the evidence is clear.
For a size read from an image, estimate it from something of known size in the picture
(a standard door is 813 x 2032 mm, a brick is about 222 mm long, a 5000 L tank is about 1.8 m tall).
Name what you used. If nothing in the picture gives a scale, leave the size out.
If the customer says they don't know a fact, set value to "unknown" and how to "said".
Leave out any fact you cannot support. An empty list is a valid answer.

Also report: job (one of the job keys below, or null), image_quality (good, blurry, dark, wrong_subject),
and safety (a list from: broken_glass, exposed_wiring, cracked_lintel, old_sheeting, none).

Facts for this business:
{rendered facts: key, label, type, unit, allowed values with labels and hints, look_for}

Return only JSON:
{"job": ..., "facts": [{"key", "value", "how", "evidence", "confidence"}], "image_quality": ..., "safety": [...]}
```

The adapter validates this against a Pydantic model built from the playbook. A value outside `allowed` is dropped, and so is a unit mismatch. `how: seen` becomes `INFERRED`. `how: said` becomes `STATED`. The SAM call keeps its role: it segments the objects named in the evidence, and its score caps the confidence. The model can't claim 0.9 on a door that SAM scores at 0.5.

### 6.2 Phrase: the step into a WhatsApp message

Model: Muse Spark 1.3, low effort. No tools, no rate card and no policy in the context, only the step and the last few messages.

```
{preamble}
You are texting a customer on WhatsApp for {business_name}. Tone: {tone}. Languages: {languages}.
Write the next message. Code has already decided what it must do; you only choose the words.

The step:
{step as JSON: kind, job_label, known, assumptions, question, choices, accept_unsure, quote, inspection, sentence}

How to write each kind:
- confirm: say what you think and why, using the evidence, in one or two short sentences. Then ask
  for a yes or a correction. Example: "From your photo it looks like a solid meranti door, about 0.8 m
  wide (I compared it with the frame). Is that right?"
- ask: if "known" is not empty, start with a short recap so they see you listened. Ask the question.
  If there are choices, give each label with its hint on its own line, numbered.
  If accept_unsure is true, say that "not sure" is fine.
- quote / inspection / escalate: use the sentence as the content. Only add a greeting or the customer's name.
Answer anything the customer asked that "known" or the step covers, in one sentence, before the step.
Never write a number, price, date, product or promise that is not in the step.
One message, under 60 words for ask and confirm. No headings, no markdown except numbered choices.
```

`check_reply` keeps its job and adds three checks. An `ask` or `confirm` reply must end with a question. A `confirm` must contain each `value_label`. No number may appear that is not in the step. If any check fails, one retry, then `step.sentence`. `sentence` is built by code from the same structure, so the fallback says the same thing in a plainer voice. It never changes the meaning.

### 6.3 The turn model with tools

This shrinks. With the read and phrase calls in place, the only tools the model still chooses are the customer-led ones: `check_availability`, `accept_quote`, `create_deposit_link`, `hold_slot` and `request_change`. `update_case`, `get_quote`, `book_inspection` and `escalate_to_owner` are called by the turn from the step. Remove from `PLATFORM_TASK` every line that steers the flow: "offer the descriptions", "lead to one outcome", "call get_quote in that same turn", and the size-estimate rule. A turn is then: read, then plan, then optionally the tool model when the customer asked for an action, then phrase. That is three model calls at most, under the four-call cap.

## 7. Worked examples

**Door showroom, photo only.** The read returns `material=meranti, seen, 0.82, "red-brown grain, raised panels"`, `door_type=single_entrance, seen, 0.9` and `width_m=0.81, seen, 0.7, "matches a standard 813 frame"`. The planner checks `decides: outcome` first, finds `opening` (replacement or new) missing, and sees that inferences are pending. The confirm step comes first.

> From your photo it looks like a single solid meranti front door, standard width (about 0.8 m). Is that right? And is this replacing the door in that same frame?

The customer replies "yes but I want it wider, like a pivot". The read gives `door_type=pivot, said`, which becomes `stated`. That contradicts the inference, so `door_type` is now `stated`. Material and opening are confirmed. Width is still needed, because widening the opening is an `outcome` fact, and the inspection trigger S01 fires.

> Got it: a meranti pivot door, wider than the current opening. Widening an opening needs a site measure first. It's R 500, credited against your order. The earliest slot is Tuesday morning. Shall I book it?

**Carport, customer unsure.** Text: "how much for a carport for 2 cars". The read returns `job=carport` and `bays=2, said`. Width and length are missing, so the planner asks the easy one first: sheeting is `easy` and `decides: price`.

> Happy to help with a double carport. Which roof would you like?
> 1. Galvanised IBR sheeting – the standard metal roof, most affordable
> 2. Polycarbonate – lets light through, cooler underneath
> Not sure is fine – a photo of where it'll go also helps.

"No idea." That makes `sheet=unknown`, and `if_unsure: range` applies. The planner asks the size next: a "standard double carport is about 6 x 6 m; is that roughly your space?" is a confirm built from a playbook default, marked `inferred` with the evidence "standard double". A yes leads to an indicative range across both sheets. It is never a fixed quote.

**Tank, everything known.** "Need to swap my 5000 L JoJo, same spot, base is level." The read gives `size_litres=5000`, `replacement=yes` and `existing_level_base=yes`, all `said`. They are `stated` and `price_ready`, so the planner quotes in this turn. This is the case the three small-set misses cover.

## 8. Evaluation

The small set runs against the live model from now on. A planner-only run is kept as a unit test, not as the gate. New conversations per business, written with the customer simulator:

| Case | Pass when |
|---|---|
| knows-all | quotes on the first turn; no question repeats a stated fact |
| knows-nothing | the first reply has 2–4 labelled choices and no internal keys; no price before facts are resolved |
| photo-confirm | the first reply states at least one assumption with its evidence and ends with a question; it does not list every option |
| photo-contradicted | the customer's correction wins; the quote uses the corrected value |
| photo-low-confidence | no assumption is stated; it asks with choices and suggests a clearer photo |
| unsure-twice | no third ask; range or inspection, as the playbook says |
| mixed (voice then photo) | facts from both are merged; no re-ask |

New metrics in `run_gate`: re-ask rate (target 0), assumptions with evidence, choices shown while a usable inference existed (target 0), and quotes issued on `inferred`-only facts (must be 0, a hard gate).

## 9. Build order

The Saturday demo needs items 1–5. Items 6–8 can land before submission on 4 November.

1. Rename the door tenant to a fictional name in the README, the tests and the eval set (finding 12). 15 minutes.
2. Fix the fee label: `fee_item` priced from the rate card. 30 minutes.
3. Playbook fields (section 4), plus a door seed under the fictional name, with `material`, `door_type`, `opening` and `width_m` as facts and the options from the demo rate card. Move the sheet into a FrameWorks fact. Half a day.
4. Fact state and `price_ready` (section 3), with domain tests. Half a day.
5. Read prompt and validated output (6.1); confirm step and question ranking in the planner (section 5). One day.
6. Phrase prompt and the narrowed turn (6.2, 6.3); the `check_reply` additions. Half a day.
7. Live-model small set with the new cases (section 8). Half a day, plus credits.
8. Make `_checks` default to not met for photo-sourced facts; apply L01 and L02. Two hours.

If Saturday comes first, a cut-down 3 and 5 is enough to show the door demo. Run the read prompt on a door photo and have the planner produce a `CONFIRM` from it, even with the old phrasing path. That is the moment the owner will remember.

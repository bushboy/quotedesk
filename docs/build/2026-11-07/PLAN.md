# Carport picture

Written 1 November 2026. The decisions are in [carport-picture.md](design/carport-picture.md). Tick a box only when that item is actually done. One commit per numbered section.

FrameWorks only. The quote still goes out if the drawing fails. Tests pass a fake renderer. They do not call Muse Image, and they do not log the bytes.

## The model

Muse Image, `muse-image-1.0`.

- Edit the customer's garage photo with `POST /v1/images/edits`.
- Generate the imaginary wall and garage with `POST /v1/images/generations`.
- Muse Spark keeps the conversation. SAM 3.1 keeps segmentation. Neither draws this picture.

## Rules

- The picture illustrates a confirmed spec. It is not a price fact and it does not confirm a size.
- Shade net is drawn with a curved roof. Solid IBR and insulated sheeting stay straight. A sheet curves only when the playbook says it sags.
- Web search and image search on Muse Image stay off.
- The quote is sent before the picture. A slow or failed drawing does not change the total.
- Fictional tenants only. A test's expected quote sentence changes only where this plan says the reply also carries a drawing.
- `CARPORT_PICTURE` defaults to `off`. Off builds no renderer and leaves the quote path untouched. On is the only way a picture is attempted.

## 1. Design

- [x] Write the decisions in `docs/build/2026-11-07/design/carport-picture.md`.
- [x] `CARPORT_PICTURE=off` is in `.env.example` and the local env file. Unset is off. `on` is the only value that enables it.
- [x] The turn, `get_quote`, the planner, and the prompts do not read the flag. That stays true until the picture slice adds one optional renderer call after the quote sentence.

## 2. Renderer

- [x] The composition root builds the renderer only when `CARPORT_PICTURE` is `on`. Off passes nothing, and the turn returns before any drawing.
- [x] A port returns image bytes, or fails. The turn never sees the Meta URL.
- [x] `muse-image-1.0` is called for FrameWorks only, with `META_API_KEY` and the existing Meta base URL.
- [x] An edit posts the customer photo. A generation posts no photo.
- [x] `enable_web_search` and `enable_image_search` are false. `reasoning_strength` is `high`.
- [x] The bytes, the prompt, and the key are not logged.
- [x] No key, or a failed call, returns no picture. The quote sentence is unchanged.

## 3. What is drawn

- [x] The playbook marks `SHADE-NET` as a sagging sheet. The prompt asks for a curved roof on that sheet.
- [x] `SHEET-ECO`, `SHEET-COLOUR`, and `SHEET-INSUL` stay a straight pitched roof.
- [x] The prompt uses the confirmed sheet label, width, and length. A gutter and a frame finish are included when they are known.
- [x] The prompt contains no rand amount and no brand.
- [x] A range, an escalation, and a site measure draw nothing.
- [x] AquaSure never calls the renderer.

## 4. Onto their garage, or an imaginary one

- [x] The latest usable customer photo of a garage, wall, or house is the edit input.
- [x] No photo, or `media_usable` false, generates the carport against a plain wall and a single garage.
- [x] The reply says the drawing used their photo, or that the photo was hard to use and the drawing is imaginary.
- [x] The picture follows the quote. The quote total is the same sentence as today, then the drawing.

## 5. Tests

- [x] A confirmed shade-net carport with a garage photo asks for an edit and a curved roof. The quote total is unchanged.
- [x] A confirmed IBR carport with no photo asks for a generation and a straight roof.
- [x] A blurry photo asks for a generation, and the reply says the photo was hard to use.
- [x] A renderer failure still sends the quote and no picture.
- [x] AquaSure sends no picture.
- [x] With `CARPORT_PICTURE` off, a confirmed FrameWorks quote sends the same sentence as today and no picture.
- [x] The tests pass the renderer in. They do not call Muse Image.
- [x] `pytest` is green. 477 passed.

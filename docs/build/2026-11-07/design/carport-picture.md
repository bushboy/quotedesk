# Carport picture

Written 1 November 2026. FrameWorks can show a picture of the carport with the quote. AquaSure does not. The picture illustrates the confirmed spec. It does not set a size, a sheet, or a price.

## The switch

`CARPORT_PICTURE` is `off` or `on`. Unset is off. The local env file and `.env.example` set it to `off`.

While it is off, nothing draws. The turn, `get_quote`, the planner, and the prompts do not read the flag and do not mention Muse Image. The quote sentences stay as they are.

When the picture is built, the composition root is the only place that reads the flag. Off means it passes no renderer. On means it passes one. The turn calls that renderer only when it was passed in, and only after the quote sentence is already chosen. A missing renderer returns before any drawing code. AquaSure and a switched-off FrameWorks process take that return.

## The model

The picture is drawn by Muse Image, model id `muse-image-1.0`, on the same Meta base URL the app already uses (`https://api.meta.ai/v1`) and the same `META_API_KEY`.

Two calls, one model:

- A photo of the garage, wall, or house is already on the case: `POST /v1/images/edits`. The prompt tells the model to keep that building and add the carport onto it.
- No usable photo: `POST /v1/images/generations`. The prompt describes the same carport against a plain plastered wall and a single garage.

Muse Spark stays the conversation model. It does not draw pixels. SAM 3.1 (`sam-3.1`) stays the segmenter. It does not draw the picture. Muse Image web search and image search are turned off (`enable_web_search` and `enable_image_search` false) so the drawing does not copy a real brand. `reasoning_strength` stays `high` so an edit keeps the garage. The quote is sent first. The picture follows. A slow drawing does not hold the price.

## Which photo

The photo is the latest customer image on the case that the read already treated as a garage, a wall, or a house. The edit sends those bytes. The caption and the photo notes can name what is in the picture. They are not a new price fact.

A blurry or unreadable photo is not the background. `media_usable` false means the drawing uses the imaginary wall instead, and the reply says the photo was hard to use. A missing photo uses the imaginary wall. There is no second upload for the business owner in this slice.

## The roof

The playbook says which sheet sags. A sagging sheet is drawn as a curved roof. Shade net (`SHADE-NET`) sags: it is cloth, not a solid sheet, and the roof drapes in a curve between the posts. Galvanised IBR, colour-coated IBR, and insulated sheeting stay a straight pitched roof. Polycarbonate stays straight until the playbook marks it curved. The curve is a drawing instruction. It does not change the price.

The prompt names the confirmed sheet, the width and length in metres, a gutter when they asked for one, and a painted or galvanised frame when that is known. It does not name a rand amount, a quote id, or a brand.

## When it is drawn

The picture is drawn once the spec is confirmed and the sheet, the width, and the length are known. A price range, because the sheet is still open, draws nothing. An escalation or a site measure draws nothing. A failed drawing leaves the quote as it was sent. The customer is told the drawing did not come through.

The reply that carries the picture says it is a drawing of the confirmed spec, not a measure. The bytes are not logged.

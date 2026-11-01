# Voice notes

Written 1 November 2026. A WhatsApp voice note is the customer speaking. The reply plays back the transcript. A spoken yes confirms the spec only when the speech engine is sure. Otherwise the customer types the yes.

## What already exists

`VoiceTranscriber` and `MuseVoice` turn an audio event with no transcript into text. The receive path copies that text onto the message, and the conversation event body is the transcript. The planner then reads that body as what the customer said. A failed or empty transcript sends "I couldn't hear that voice note. Please type the details." and stores nothing. An audio event that already has a transcript skips the adapter. Muse is called only when `MUSE_BASE_URL` is set.

The chat page already records a voice note and posts it as a WhatsApp audio message. That message has a media id and no transcript.

The spec replay ends with "Is that the spec to price?" `accept_spec_reply` treats yes, yep, yeah, and correct as `spec_confirmed`. It does that from the event body, so a spoken yes that transcribes cleanly would confirm today, with no score attached. A typed yes stays that path.

Photo notes are named on the replay and are not a price key. Speech confidence is not part of `derive_confidence`.

## Playback

The outbound reply for a turn whose latest customer message is audio begins with "I heard: {transcript}." The turn adds that prefix after the model reply, so the wording stays the transcript. A second copy is not added when the reply already starts with it.

The transcript remains the event body. The turn may record price facts from those words, the same way it records a typed message. The playback sentence is not itself a fact. A fixed quote still waits for the spec replay.

## A spoken yes

The yes words stay the ones `accept_spec_reply` already accepts. A spoken no uses the same bar before the spec is declined.

The speech engine returns a score from 0 to 1, or nothing. A spoken yes or no on the spec is used when the score is at least 0.8. The reply still starts with "I heard: {transcript}." and then the quote, or the decline.

A missing score, or a score below 0.8, does not set `spec_confirmed` and does not decline it. The reply is:

"I heard: {transcript}. I'm not sure I heard that clearly. Please confirm by typing. Is that the spec to price?"

The spec question stays in that sentence, so a later typed yes still matches. No quote goes out on the unsure turn.

This gate applies when the previous reply asked "Is that the spec to price?" A voice note that states the job, the size, or the material is the customer's message. It is played back and read. It is not held for a typed copy, because the replay still has to be confirmed before a fixed quote.

The score is not written into `required_fields`, `media_usable`, or `rate_card`. `derive_confidence` does not read it.

## The engine

`transcribe` returns the text and a `Decimal` score, or `None` when the response has no score. `MuseVoice` maps the score the transcription JSON already carries onto 0 to 1. A response with no score, or a score this adapter cannot map, returns `None`. The adapter does not invent a number. It does not log the bytes, the transcript, or the score.

Until a captured Muse response shows the field name, the adapter returns `None` for the score. Tests supply the score themselves. They do not call Muse.

## Where the score lives

The receive path runs, then the turn runs. The score has to be on the stored message or the turn cannot see it. `InboundMessage` gains `transcript_confidence`. A new migration adds `inbound_message.transcript_confidence`, nullable numeric. Applied migrations stay as they are. A missing column value is the same as `None`: an unsure spoken yes asks for a typed yes.

An audio event that already carries a transcript still skips the adapter. With no score stored, a spoken yes on the spec asks for a typed yes. The simulator and the tests set the score when that spoken yes should count.

## Left as they are

An empty transcript, a missing media id, and an adapter error keep the existing type-it sentence. Nothing is stored, and there is no "I heard" line.

`prompts.py` stays unchanged. The turn adds the playback prefix.

The chat recorder stays. This slice does not add a second way to record.

The real WhatsApp sender stays out. The language check runs again on the transcript after it is heard, because today it runs before transcription and an empty transcript skips it.

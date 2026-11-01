# Voice notes

Written 1 November 2026. The decisions are in [voice-notes.md](design/voice-notes.md). Tick a box only when that item is actually done. One commit per numbered section. A design box is ticked when the design file exists. A test box is ticked when the test fails for the reason named here, or passes once the behaviour is in.

The chat page already records a voice note and posts it with no transcript. `MuseVoice` already returns text when `MUSE_BASE_URL` is set. A failed transcript already asks the customer to type. This plan adds the playback and the confidence gate. It does not add a sender, a second recorder, or a live Muse call in the tests.

## Rules

- A voice note is played back as "I heard: {transcript}." The turn adds that prefix, so the model cannot drop the transcript.
- Those words are the customer's message. A fixed quote still waits for the spec replay.
- A spoken yes or no on "Is that the spec to price?" counts when the speech score is at least 0.8.
- A missing score, or a score below 0.8, leaves `spec_confirmed` unset. The reply asks them to type, and it still asks "Is that the spec to price?"
- The score is not a quote-confidence input. `derive_confidence` stays as it is.
- The adapter does not invent a score, and it does not log the audio, the transcript, or the score.
- A test's expected outcome changes only where this plan says the behaviour changes.
- `run_agent_turn.py` stays one file. Applied migrations stay as they are. Fictional tenant names only.

## 1. Design

- [x] Write the decisions in `docs/build/2026-11-06/design/voice-notes.md`.

## 2. Score on the transcript

- [x] `VoiceTranscriber.transcribe` returns the text and a score from 0 to 1, or no score.
- [x] `MuseVoice` reads the score the transcription JSON already has. No score comes back as no score.
- [x] `InboundMessage` carries `transcript_confidence`.
- [x] A new migration adds nullable `inbound_message.transcript_confidence`. The memory store and `StoredUnit` keep it with the message.
- [x] An audio event that already has a transcript still skips the adapter.
- [x] A failed or empty transcript still sends "I couldn't hear that voice note. Please type the details." and stores nothing.
- [x] The language check runs on the transcript after it is heard.

## 3. Play back what we heard

- [x] The reply after a voice note begins with "I heard: {transcript}."
- [x] The prefix is added once. A reply that already starts with it is left as it is.
- [x] The transcript stays the event body, so the turn can record facts from it.
- [x] The playback sentence is not stored as a price fact.
- [x] Test: a voice note whose words state a 5000 L swap is answered with "I heard:" and those words, and the turn does not send the fixed quote yet.

## 4. A spoken yes

- [x] After the spec replay, a voice note that says yes with a score of 0.8 or more sets `spec_confirmed` and the fixed quote goes out.
- [x] The quote reply still begins with "I heard:".
- [x] A score below 0.8, or no score, does not set `spec_confirmed` and does not send a quote.
- [x] That reply is "I heard: {transcript}. I'm not sure I heard that clearly. Please confirm by typing. Is that the spec to price?"
- [x] A typed yes on the following turn sends the fixed quote. The existing typed-yes tests stay green.
- [x] A spoken no uses the same 0.8 bar before the spec is declined.
- [x] A voice note that is not answering the spec replay is played back and read as the message. It is not held for a typed copy.

## 5. Tests

- [ ] The three receive tests stay: a transcript skips the adapter, a missing transcript uses it, a failure asks the customer to type.
- [ ] New tests cover a sure spoken yes, an unsure spoken yes, a missing score, a spoken no below the bar, and the playback sentence.
- [ ] The tests pass the score in. They do not call Muse, and they do not log the audio.
- [ ] `pytest` is green. Record the count.

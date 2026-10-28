# Saturday designs

Block A, Block B, and Block C are written. The working list is [the Saturday plan](../PLAN.md). A design file is written only when its boxes there are being ticked. A test starts only after that file's boxes are ticked.

[whatsapp-simulator-learnings.md](whatsapp-simulator-learnings.md) is input for `harness.md`, `run-agent-turn.md`, `inbound-gate.md`, and `click-path.md`. It is not one of those designs. Read it before writing them.

[whatsapp-simulator-handoff.md](whatsapp-simulator-handoff.md) is for a second team joining the simulator. It says what is already built and which files they may edit. It adds no box.

| File | Artifact | Block |
| --- | --- | --- |
| [request-change.md](request-change.md) | `RequestChange` | A |
| [commitment-checker.md](commitment-checker.md) | The pure check over a draft reply | A |
| [inbound-gate.md](inbound-gate.md) | `ReceiveInboundEvent` and the input gate | B |
| [update-case.md](update-case.md) | `UpdateCase` | B |
| [run-agent-turn.md](run-agent-turn.md) | Quiet window, lock, `RunAgentTurn`, handover | B |
| [harness.md](harness.md) | Cloud API scenario runner and the outbox read | B |
| [schedule-tools.md](schedule-tools.md) | `CheckAvailability` and `HoldSlot` | B |
| [quote-status.md](quote-status.md) | `GetQuoteStatus` | B |
| [deposit-link.md](deposit-link.md) | `CreateDepositLink` | B |
| [persistence.md](persistence.md) | Tables, row-level security, insert-only audit | C |
| [click-path.md](click-path.md) | AquaSure seed, web chat, card from status | C |

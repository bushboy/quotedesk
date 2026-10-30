# Planner

Written 30 October 2026. Increment 3 of the production plan. The domain function and the turn wiring below are the whole of this increment. Inspection booking, the unknown fact state, and the owner notification are increment 4.

`plan_next_step(case, playbook, policy)` is pure. It returns one step for the conversation. Each job is planned on its own. The conversation step is the earliest of escalate, inspection, ask, then quote.

A required playbook fact that is missing is an ask, and the sentence is that fact's question. No trade name is consulted. When every required fact is present, `decide()` chooses inspection, escalation, or a quote. Confidence flags that have not been stored yet are treated as met, so a case is not escalated only because the turn has not measured confidence. A policy with no rules, or a job type the playbook does not name, is ready to quote once its required facts are present.

The platform prompt keeps today's instructions and appends the step. The model phrases that step. It does not choose a different one.

The five reply rewriters are deleted in the same change. An empty reply, or a reply that fails `check_reply`, is replaced by the planner sentence. After a tool has run, that sentence is built from the tool result, so it can carry a price, a date, or an inclusion only when the tool returned it. A raised exception still escalates with the handover sentence.

`conversation_id`, `job_id`, and `quote_id` are filled by the turn. They are absent from the tool schemas. A turn calls the model at most four times. Tool results go back as `function_call_output` items. Invalid tool JSON, and tool arguments that fail the input model, are returned to the model once; a second failure escalates. Extraction calls use medium reasoning effort. Phrasing calls use low. The adapter records the latency of each call.

`RunAgentTurn` takes the case repository. It does not read `HandoverToHuman._cases`.

`update_case` rejects the alias keys `tank_size`, `size`, `dimensions`, `item`, and `job`. Where the playbook defines facts for the job type, any other key outside that list and the platform bookkeeping keys is rejected. Number and yes/no values are normalised. `GetQuote` reads the canonical keys only.

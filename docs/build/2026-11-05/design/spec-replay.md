# Spec replay

Written 1 November 2026. A fixed quote waits until the customer has confirmed the spec. Media can suggest a value. It does not set the price.

## What is confirmed

The spec is the price facts on the job: each required playbook fact that is stated or confirmed, in the words the playbook already uses. A settled clash is part of that spec. The replay names every one of those facts and every settled clash, and it ends with "Is that the spec to price?"

A yes on that replay stores `spec_confirmed` true. The next step may be the fixed quote. A no stores `spec_confirmed` false. The fixed offer is then withheld. `decide` runs again with the required-field check open, so a range rule can match. If a fixed rule would still match, the outcome becomes an indicative range. The result has no fixed total.

An open required fact is still asked. It does not become a fixed quote. If the customer cannot answer, the playbook's existing range, inspection, or escalation stands.

`agreement` stays out of this decision.

## A clash

A clash is a price fact the customer stated and a photo or video reading of a different value. Both values are kept. The customer's value stays the current one, so a photo reading cannot replace it. The evidence fact is stored and superseded, which keeps a single current value.

The step asks once: "You said {customer}. The photo looks like {evidence}. Which should I price?" The answer stores `clash:{key}` as `customer` or `evidence`, and the chosen value. A later step does not ask that clash again. A new reading with a different value clears the stored side and the spec confirmation, and the clash is asked again.

Two stated sources that already disagree stay contested, as they are today.

## What may be priced

An inferred photo size stays out of `ready_values` until the customer confirms it. Confirming the spec confirms those inferred facts. A confirmed size counts as `customer_stated` for the fixed-offer rules.

The planner returns the replay instead of a fixed quote while `spec_confirmed` is not true. A turn that follows that step does not choose a quote yet. A direct `get_quote` on a fully stated spec that was not declined still prices the fixed offer. That is the path the scripted turn uses. A declined spec, or a clash that has not been chosen, does not return a fixed total from `get_quote`.

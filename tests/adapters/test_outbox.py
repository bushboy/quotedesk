def test_outbox_appends_one_pending_row():
    from quotedesk.adapters.outbound.channels.outbox import Outbox, OutboxMessage

    outbox = Outbox()
    assert outbox.pending() == ()
    message = outbox.append("The tank in the yard is leaking.")
    assert type(message) is OutboxMessage
    assert message.body == "The tank in the yard is leaking."
    assert message.status == "pending"
    assert outbox.pending() == (message,)
    assert Outbox().pending() == ()
    assert not hasattr(outbox, "send")


def test_a_restarted_outbox_never_reuses_an_id(monkeypatch):
    from quotedesk.adapters.outbound.channels import outbox as module

    started = 1_790_000_000_000 * 1_000_000
    monkeypatch.setattr(module.time, "time_ns", lambda: started)
    before = module.Outbox()
    seen = [before.append(f"Reply {index}.").id for index in range(50)]
    monkeypatch.setattr(module.time, "time_ns", lambda: started + 5_000 * 1_000_000)
    after = module.Outbox().append("After the restart.")
    assert seen == sorted(seen)
    assert after.id > max(seen)

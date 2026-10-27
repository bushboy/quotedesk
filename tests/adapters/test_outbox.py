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

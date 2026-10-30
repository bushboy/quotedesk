"""One notice per escalation. WhatsApp to the playbook number, otherwise email."""


class NotifyOwner:
    def __init__(self, notices, sender, mail=None) -> None:
        self._notices = notices
        self._sender = sender
        self._mail = mail

    def send(self, tenant_id, playbook, conversation_id, body: str) -> str:
        if self._notices.already(tenant_id, conversation_id):
            return ""
        number = playbook.owner_whatsapp.strip()
        email = playbook.owner_email.strip()
        channel = ""
        if number:
            try:
                self._sender.send(number, body)
                channel = "whatsapp"
            except Exception:
                channel = ""
        if not channel and email and self._mail is not None:
            self._mail.send(email, body)
            channel = "email"
        if channel:
            self._notices.record(tenant_id, conversation_id, channel)
        return channel

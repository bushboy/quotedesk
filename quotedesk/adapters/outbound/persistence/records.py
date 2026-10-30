"""Case, conversation, and schedule rows.

These classes set the tenant for the transaction, then read and write.
"""

from uuid import UUID

from sqlalchemy import text
from sqlalchemy.engine import Connection

from quotedesk.domain.case.case_file import CaseFact, CaseFile, Job
from quotedesk.domain.conversation.events import Conversation, ConversationEvent
from quotedesk.domain.quotes.schedule import ScheduleCommitment


def bind_tenant(connection: Connection, tenant_id: UUID) -> None:
    connection.execute(
        text("SELECT set_config('app.current_tenant_id', :tenant_id, true)"),
        {"tenant_id": str(tenant_id)},
    )


def hold_conversation(connection: Connection, tenant_id: UUID, conversation_id: UUID) -> bool:
    """True when this tenant owns the conversation row.

    The primary key is the conversation id alone. An insert that conflicts with
    another tenant's row is invisible under row-level security, so a following
    read would miss the message. `ON CONFLICT DO NOTHING` is not ownership.
    """
    connection.execute(
        text(
            """
            INSERT INTO conversation (conversation_id, tenant_id)
            VALUES (:conversation_id, :tenant_id)
            ON CONFLICT (conversation_id) DO NOTHING
            """
        ),
        {"conversation_id": conversation_id, "tenant_id": tenant_id},
    )
    row = connection.execute(
        text(
            """
            SELECT 1 FROM conversation
            WHERE tenant_id = :tenant_id AND conversation_id = :conversation_id
            """
        ),
        {"tenant_id": tenant_id, "conversation_id": conversation_id},
    ).first()
    return row is not None


class CaseTables:
    def save(self, connection: Connection, case: CaseFile) -> None:
        bind_tenant(connection, case.tenant_id)
        connection.execute(
            text("DELETE FROM case_fact WHERE conversation_id = :conversation_id"),
            {"conversation_id": case.conversation_id},
        )
        connection.execute(
            text("DELETE FROM case_file WHERE conversation_id = :conversation_id"),
            {"conversation_id": case.conversation_id},
        )
        connection.execute(
            text(
                """
                INSERT INTO case_file (conversation_id, tenant_id)
                VALUES (:conversation_id, :tenant_id)
                """
            ),
            {"conversation_id": case.conversation_id, "tenant_id": case.tenant_id},
        )
        for job in case.jobs:
            for fact in job.facts:
                connection.execute(
                    text(
                        """
                        INSERT INTO case_fact (
                            fact_id, tenant_id, conversation_id, job_id, job_type, job_status,
                            key, value, source, event_id, superseded_by, contested
                        )
                        VALUES (
                            :fact_id, :tenant_id, :conversation_id, :job_id, :job_type, :job_status,
                            :key, :value, :source, :event_id, :superseded_by, :contested
                        )
                        """
                    ),
                    {
                        "fact_id": fact.fact_id,
                        "tenant_id": case.tenant_id,
                        "conversation_id": case.conversation_id,
                        "job_id": job.job_id,
                        "job_type": job.job_type,
                        "job_status": job.status,
                        "key": fact.key,
                        "value": fact.value,
                        "source": fact.source,
                        "event_id": fact.event_id,
                        "superseded_by": fact.superseded_by,
                        "contested": fact.contested,
                    },
                )

    def get(self, connection: Connection, tenant_id: UUID, conversation_id: UUID) -> CaseFile | None:
        bind_tenant(connection, tenant_id)
        row = connection.execute(
            text(
                """
                SELECT conversation_id FROM case_file
                WHERE tenant_id = :tenant_id AND conversation_id = :conversation_id
                """
            ),
            {"tenant_id": tenant_id, "conversation_id": conversation_id},
        ).one_or_none()
        if row is None:
            return None
        facts = list(
            connection.execute(
                text(
                    """
                    SELECT fact_id, job_id, job_type, job_status, key, value, source, event_id, superseded_by, contested
                    FROM case_fact
                    WHERE conversation_id = :conversation_id
                    ORDER BY fact_id
                    """
                ),
                {"conversation_id": conversation_id},
            )
        )
        jobs: dict[str, dict] = {}
        for fact in facts:
            job = jobs.setdefault(
                fact.job_id,
                {"job_id": fact.job_id, "job_type": fact.job_type, "status": fact.job_status, "facts": []},
            )
            job["facts"].append(
                CaseFact(
                    fact_id=fact.fact_id,
                    job_id=fact.job_id,
                    key=fact.key,
                    value=fact.value,
                    source=fact.source,
                    event_id=fact.event_id,
                    superseded_by=fact.superseded_by,
                    contested=fact.contested,
                )
            )
        return CaseFile(
            conversation_id=conversation_id,
            tenant_id=tenant_id,
            jobs=tuple(Job(job_id=item["job_id"], job_type=item["job_type"], status=item["status"], facts=tuple(item["facts"])) for item in jobs.values()),
        )


class ConversationTables:
    def save(self, connection: Connection, tenant_id: UUID, conversation: Conversation) -> None:
        bind_tenant(connection, tenant_id)
        held = hold_conversation(connection, tenant_id, conversation.conversation_id)
        if not held:
            raise RuntimeError("That conversation belongs to another tenant.")
        connection.execute(
            text("DELETE FROM conversation_event WHERE conversation_id = :conversation_id"),
            {"conversation_id": conversation.conversation_id},
        )
        for arrival, event in enumerate(conversation.log):
            connection.execute(
                text(
                    """
                    INSERT INTO conversation_event (
                        conversation_id, tenant_id, provider_message_id, at, body, transcript_id, extraction_id, arrival
                    )
                    VALUES (
                        :conversation_id, :tenant_id, :provider_message_id, :at, :body, :transcript_id, :extraction_id, :arrival
                    )
                    """
                ),
                {
                    "conversation_id": conversation.conversation_id,
                    "tenant_id": tenant_id,
                    "provider_message_id": event.provider_message_id,
                    "at": event.at,
                    "body": event.body,
                    "transcript_id": event.transcript_id,
                    "extraction_id": event.extraction_id,
                    "arrival": arrival,
                },
            )

    def get(self, connection: Connection, tenant_id: UUID, conversation_id: UUID) -> Conversation | None:
        bind_tenant(connection, tenant_id)
        row = connection.execute(
            text(
                """
                SELECT conversation_id FROM conversation
                WHERE tenant_id = :tenant_id AND conversation_id = :conversation_id
                """
            ),
            {"tenant_id": tenant_id, "conversation_id": conversation_id},
        ).one_or_none()
        if row is None:
            return None
        events = tuple(
            ConversationEvent(
                provider_message_id=event.provider_message_id,
                at=event.at,
                body=event.body,
                transcript_id=event.transcript_id,
                extraction_id=event.extraction_id,
            )
            for event in connection.execute(
                text(
                    """
                    SELECT provider_message_id, at, body, transcript_id, extraction_id
                    FROM conversation_event
                    WHERE conversation_id = :conversation_id
                    ORDER BY at, arrival
                    """
                ),
                {"conversation_id": conversation_id},
            )
        )
        return Conversation(conversation_id=conversation_id, log=events)


class ScheduleTables:
    def save(self, connection: Connection, tenant_id: UUID, quote_id: str, commitment: ScheduleCommitment) -> None:
        bind_tenant(connection, tenant_id)
        connection.execute(
            text("DELETE FROM schedule_commitment WHERE quote_id = :quote_id"),
            {"quote_id": quote_id},
        )
        connection.execute(
            text(
                """
                INSERT INTO schedule_commitment (quote_id, tenant_id, status, sentence, earliest_window)
                VALUES (:quote_id, :tenant_id, :status, :sentence, :earliest_window)
                """
            ),
            {
                "quote_id": quote_id,
                "tenant_id": tenant_id,
                "status": commitment.status,
                "sentence": commitment.sentence,
                "earliest_window": commitment.earliest_window,
            },
        )

    def get(self, connection: Connection, tenant_id: UUID, quote_id: str) -> ScheduleCommitment | None:
        bind_tenant(connection, tenant_id)
        row = connection.execute(
            text(
                """
                SELECT status, sentence, earliest_window
                FROM schedule_commitment
                WHERE tenant_id = :tenant_id AND quote_id = :quote_id
                """
            ),
            {"tenant_id": tenant_id, "quote_id": quote_id},
        ).one_or_none()
        if row is None:
            return None
        return ScheduleCommitment(status=row.status, sentence=row.sentence, earliest_window=row.earliest_window)

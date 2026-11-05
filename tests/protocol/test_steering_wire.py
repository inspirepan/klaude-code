from klaude_code.protocol import events, message, op


def test_steering_keeps_published_wire_names() -> None:
    operation = op.SteerAgentOperation(session_id="session-test", input=message.UserInputPayload(text="queued"))
    operation_payload = operation.model_dump(mode="json")
    assert operation_payload["type"] == "follow_up_agent"
    assert op.SteerAgentOperation.model_validate(operation_payload) == operation

    event = events.SteeringQueueUpdatedEvent(session_id="session-test", texts=["queued"])
    assert events.event_type_name(event) == "follow.up.queue.updated"
    envelope = events.EventEnvelope(
        event_id="event-test",
        event_seq=1,
        session_id=event.session_id,
        event_type=events.event_type_name(event),
        durability=events.event_durability(events.event_type_name(event)),
        timestamp=event.timestamp,
        event=event,
    )
    assert events.parse_event_envelope_json(envelope.model_dump_json(serialize_as_any=True)) == envelope

    interrupt = op.InterruptOperation(session_id="session-test", resume_follow_ups=True)
    interrupt_payload = interrupt.model_dump(mode="json")
    assert interrupt_payload["resume_follow_ups"] is True
    assert "resume_steering" not in interrupt_payload
    assert op.InterruptOperation.model_validate(interrupt_payload) == interrupt

    interrupted = events.InterruptEvent(session_id="session-test", resume_follow_ups=True)
    interrupted_payload = interrupted.model_dump(mode="json")
    assert interrupted_payload["resume_follow_ups"] is True
    assert "resume_steering" not in interrupted_payload
    assert events.parse_event("interrupt", interrupted_payload) == interrupted

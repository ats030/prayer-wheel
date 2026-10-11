"""Cancellable public Wikipedia pipeline; no private server/JobStore imports."""
import multiprocessing
import os
import time


def generate_child(query_text, connection):
    try:
        # The source route is operator-owned, never supplied in the HTTP body.
        os.environ["TIMELINE_SOURCE"] = "wikipedia"
        from timeline import SOURCE, build_timeline, parse_query
        if SOURCE != "wikipedia":
            raise ValueError("Wikipedia route required")
        connection.send(build_timeline(parse_query(query_text), connection.send))
    except Exception:
        connection.send({"kind": "error"})
    finally:
        connection.close()


def bounded_generation(query_text, emit, stopping, *, time_limit=3600, child=generate_child):
    if not 0 < time_limit <= 3600:
        raise ValueError("Invalid generation time limit")
    if stopping.is_set():
        return
    context = multiprocessing.get_context("spawn")
    receiver, sender = context.Pipe(duplex=False)
    process = context.Process(target=child, args=(query_text, sender), daemon=True)
    started = time.monotonic()
    deadline = started + time_limit
    checkpoint = None
    reason = "processing_error"
    try:
        process.start()
        sender.close()
        while time.monotonic() < deadline:
            if stopping.is_set():
                return
            try:
                if receiver.poll(min(0.2, max(0, deadline - time.monotonic()))):
                    record = receiver.recv()
                    if not isinstance(record, dict):
                        break
                    if record.get("kind") == "checkpoint":
                        if record.get("events"):
                            checkpoint = record
                    elif record.get("kind") == "result":
                        emit(record)
                        return
                    elif record.get("kind") == "error":
                        break
                elif not process.is_alive():
                    break
            except (EOFError, OSError):
                break
        else:
            reason = "time_limit"
        if checkpoint and not stopping.is_set():
            from timeline import parse_query, partial_result
            partial = partial_result(parse_query(query_text), checkpoint, started, reason)
            # Parent validation imports can retain a private source default; provenance
            # here comes exclusively from the isolated child, never an uploaded label.
            partial["source_mode"] = checkpoint.get("source_mode")
            emit(partial)
    finally:
        receiver.close()
        sender.close()
        if process.pid is not None:
            if process.is_alive():
                process.terminate()
            process.join(timeout=2)
            if process.is_alive():
                process.kill()
                process.join(timeout=2)
            process.close()

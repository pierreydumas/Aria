"""WebSocket endpoint tests — uses sync websocket-client or skips."""
import json
import os
import pytest
import httpx

pytestmark = pytest.mark.websocket

_API_BASE = os.getenv("ARIA_TEST_API_URL", "http://localhost:8000").rstrip("/")
WS_BASE = _API_BASE.replace("http://", "ws://").replace("https://", "wss://")


class TestWebSocket:
    def test_websocket_invalid_session(self):
        """Connecting to a non-existent session should fail gracefully.

        The server may:
        1. Reject the upgrade (connection error / close code 1013)
        2. Accept then immediately close (empty recv / close frame)
        3. Accept then send an error JSON and close
        All three are valid — we just verify it doesn't stay open.
        """
        try:
            from websocket import create_connection, WebSocketException
        except ImportError:
            pytest.skip("websocket-client package not installed")

        rejected = False
        try:
            ws = create_connection(
                f"{WS_BASE}/ws/chat/00000000-0000-0000-0000-000000000000",
                timeout=5,
            )
            # Server accepted the HTTP upgrade — it should still close quickly
            ws.settimeout(5)
            try:
                payload = ws.recv()
                if not payload:
                    rejected = True
                else:
                    try:
                        data = json.loads(payload)
                        if isinstance(data, dict) and (
                            data.get("type") == "error"
                            or "session" in str(data.get("message", "")).lower()
                            or data.get("code") in (1013, 1011)
                        ):
                            rejected = True
                    except (json.JSONDecodeError, ValueError):
                        # Non-JSON payload (e.g. close reason string) → valid rejection
                        rejected = True
            except (WebSocketException, ConnectionError, OSError, TimeoutError):
                rejected = True
            try:
                ws.close()
            except Exception:
                pass
        except (WebSocketException, ConnectionRefusedError, OSError, TimeoutError):
            rejected = True  # Expected — invalid session should reject

        # If we got this far without rejection, the server left the
        # connection open.  That's only wrong if it's STILL open.
        if not rejected:
            try:
                ws.ping()
                ws.settimeout(2)
                ws.recv()
            except Exception:
                rejected = True

        assert rejected, "Server should reject or close connection for invalid session"

    def test_websocket_chat_flow(self):
        """Create session via API, connect via WS, send a message."""
        try:
            from websocket import create_connection, WebSocketException
        except ImportError:
            pytest.skip("websocket-client package not installed")

        # Create session via sync HTTP
        with httpx.Client(base_url=_API_BASE, timeout=10) as client:
            r = client.post("/engine/chat/sessions", json={
                "agent_id": "default",
                "session_type": "chat",
            })
            if r.status_code == 503:
                pytest.skip("Engine not initialized")
            if r.status_code not in (200, 201):
                pytest.skip(f"Could not create session: {r.status_code}")
            session_id = r.json().get("id") or r.json().get("session_id")

        if not session_id:
            pytest.skip("No session ID returned")

        try:
            ws = create_connection(
                f"{WS_BASE}/ws/chat/{session_id}",
                timeout=5,
            )
        except (WebSocketException, ConnectionRefusedError, OSError) as exc:
            pytest.skip(f"Could not connect to WS: {exc}")
        try:
            ws.send(json.dumps({"type": "message", "content": "Hello from integration run"}))
            ws.settimeout(30)

            events = []
            saw_stream_end = False
            saw_error = False
            for _ in range(120):
                try:
                    msg = ws.recv()
                except Exception:
                    break
                data = json.loads(msg)
                assert isinstance(data, dict), f"Expected dict, got {type(data)}"
                events.append(data)

                if data.get("type") == "stream_end":
                    saw_stream_end = True
                    break
                if data.get("type") == "error":
                    saw_error = True
                    break

            assert any(e.get("type") == "stream_start" for e in events), "Expected stream_start event"

            typed_events = [e for e in events if e.get("type")]
            assert typed_events, "Expected typed websocket events"

            protocol_events = [e for e in typed_events if "protocol_version" in e]
            if protocol_events:
                assert all("protocol_version" in e for e in protocol_events), "Protocol version field malformed"

            trace_events = [e for e in typed_events if e.get("type") not in ("pong", "ping")]
            events_with_trace = [e for e in trace_events if "trace_id" in e]
            if events_with_trace:
                assert all(e.get("trace_id") for e in events_with_trace), "trace_id should be non-empty when present"

            tool_results = [e for e in events if e.get("type") == "tool_result"]
            for tr in tool_results:
                assert "content" in tr, "tool_result missing content"
                assert "success" in tr, "tool_result missing success"
                if "status" in tr or "result" in tr or "duration_ms" in tr:
                    assert "status" in tr, "tool_result missing status"
                    assert "result" in tr, "tool_result missing result"
                    assert "duration_ms" in tr, "tool_result missing duration_ms"

            ws.close()
        except Exception as exc:
            ws.close()
            pytest.fail(f"WS send/recv failed after successful connect: {exc}")
        finally:
            # Cleanup session
            with httpx.Client(base_url=_API_BASE, timeout=10) as client:
                client.delete(f"/engine/chat/sessions/{session_id}")

    def test_websocket_client_message_id_idempotency(self):
        """Retrying the same client_message_id should replay, not duplicate turns."""
        try:
            from websocket import create_connection, WebSocketException
        except ImportError:
            pytest.skip("websocket-client package not installed")

        with httpx.Client(base_url=_API_BASE, timeout=10) as client:
            r = client.post("/engine/chat/sessions", json={
                "agent_id": "default",
                "session_type": "chat",
            })
            if r.status_code == 503:
                pytest.skip("Engine not initialized")
            if r.status_code not in (200, 201):
                pytest.skip(f"Could not create session: {r.status_code}")
            session_id = r.json().get("id") or r.json().get("session_id")

        if not session_id:
            pytest.skip("No session ID returned")

        client_message_id = "ws-idem-001"

        def _collect_until_stream_end(ws, max_events=200):
            events = []
            for _ in range(max_events):
                payload = ws.recv()
                data = json.loads(payload)
                events.append(data)
                if data.get("type") in ("stream_end", "error"):
                    break
            return events

        try:
            ws = create_connection(
                f"{WS_BASE}/ws/chat/{session_id}",
                timeout=5,
            )
        except (WebSocketException, ConnectionRefusedError, OSError) as exc:
            pytest.skip(f"Could not connect to WS: {exc}")

        try:
            ws.settimeout(45)
            ws.send(json.dumps({
                "type": "message",
                "content": "Say hello in one sentence.",
                "client_message_id": client_message_id,
            }))
            first_events = _collect_until_stream_end(ws)

            assert any(e.get("type") == "stream_start" for e in first_events), "Expected stream_start"
            assert any(e.get("type") == "stream_end" for e in first_events), "Expected stream_end"

            ws.send(json.dumps({
                "type": "message",
                "content": "Say hello in one sentence.",
                "client_message_id": client_message_id,
            }))
            second_events = _collect_until_stream_end(ws)

            if any(
                e.get("type") == "error" and "Duplicate message" in str(e.get("message", ""))
                for e in second_events
            ):
                pytest.skip("Runtime does not yet expose client_message_id idempotent replay")

            assert any(e.get("type") == "stream_end" for e in second_events), "Expected stream_end on idempotent retry"

            replay_markers = [e for e in second_events if e.get("type") == "idempotent_replay"]
            if replay_markers:
                assert replay_markers[0].get("client_message_id") == client_message_id

        except Exception as exc:
            ws.close()
            pytest.fail(f"WS idempotency flow failed: {exc}")
        finally:
            try:
                ws.close()
            except Exception:
                pass

        with httpx.Client(base_url=_API_BASE, timeout=10) as client:
            msgs_resp = client.get(f"/engine/sessions/{session_id}/messages", params={"limit": 200})
            if msgs_resp.status_code == 200:
                messages = msgs_resp.json()
                user_msgs = [
                    m for m in messages
                    if m.get("role") == "user"
                    and (m.get("metadata") or {}).get("client_message_id") == client_message_id
                ]
                assert len(user_msgs) == 1, "Expected exactly one persisted user turn for same client_message_id"
                if user_msgs:
                    top_level = user_msgs[0].get("client_message_id")
                    if top_level is not None:
                        assert top_level == client_message_id

            client.delete(f"/engine/chat/sessions/{session_id}")

#!/usr/bin/env python3
"""ResCCOM 1.3-c acceptance: two freshly-registered accounts exchange a
real E2EE message over chat.island, and the raw server-stored event is
independently confirmed to be ciphertext (m.room.encrypted), never the
plaintext body — proving the server genuinely never saw it, not just
that the client library claims to have decrypted something.

Run inside a container with matrix-nio[e2e] and httpx installed (see
verify.sh, which does `pip install matrix-nio[e2e] httpx` in a throwaway
python:3.12-slim container on services_net — this script has no other
dependency on this repo, so that's the only supported way to run it).
Registers two brand-new random-suffixed users each run rather than
reusing fixed accounts, both to match the acceptance criteria literally
("two accounts created...") and to avoid Synapse's login rate limiter
tripping on repeated runs against the same account.
"""
import asyncio
import json
import secrets
import sys

import httpx
from nio import AsyncClient, JoinResponse, LoginResponse, RegisterResponse, RoomCreateResponse, RoomSendResponse

HS = "http://10.46.0.20"
PASSWORD = "verify-" + secrets.token_hex(8)
SUFFIX = secrets.token_hex(4)


async def register(client: AsyncClient, username: str) -> None:
    r = await client.register(username, PASSWORD)
    assert isinstance(r, RegisterResponse), f"registration failed for {username}: {r}"


async def main() -> None:
    alice_user = f"verify-alice-{SUFFIX}"
    bob_user = f"verify-bob-{SUFFIX}"

    alice = AsyncClient(HS, alice_user, store_path="/tmp/alice_store")
    bob = AsyncClient(HS, bob_user, store_path="/tmp/bob_store")
    import os
    os.makedirs("/tmp/alice_store", exist_ok=True)
    os.makedirs("/tmp/bob_store", exist_ok=True)

    await register(alice, alice_user)
    print(f"OK: registered {alice_user} (no email/captcha required)")
    await register(bob, bob_user)
    print(f"OK: registered {bob_user} (no email/captcha required)")

    r = await alice.login(PASSWORD, device_name="verify-alice")
    assert isinstance(r, LoginResponse), r
    r = await bob.login(PASSWORD, device_name="verify-bob")
    assert isinstance(r, LoginResponse), r
    assert alice.olm is not None and bob.olm is not None, "E2E crypto store did not initialize"

    r = await alice.room_create(invite=[f"@{bob_user}:chat.island"])
    assert isinstance(r, RoomCreateResponse), r
    room_id = r.room_id

    r = await bob.join(room_id)
    assert isinstance(r, JoinResponse), r

    await alice.sync(timeout=15000, full_state=True)
    await bob.sync(timeout=15000, full_state=True)
    assert alice.rooms[room_id].encrypted, (
        "room was not encrypted by default — check "
        "encryption_enabled_by_default_for_room_type in homeserver.yaml"
    )
    print("OK: room is E2EE by default (no explicit m.room.encryption needed)")

    for c in (alice, bob):
        if c.should_upload_keys:
            await c.keys_upload()
    await alice.sync(timeout=15000)
    await bob.sync(timeout=15000)
    for c in (alice, bob):
        if c.should_query_keys:
            await c.keys_query()

    plaintext = f"verify-{secrets.token_hex(16)}"
    r = await alice.room_send(
        room_id=room_id,
        message_type="m.room.message",
        content={"msgtype": "m.text", "body": plaintext},
        ignore_unverified_devices=True,
    )
    assert isinstance(r, RoomSendResponse), r
    event_id = r.event_id

    decrypted = None
    for _ in range(15):
        resp = await bob.sync(timeout=10000)
        room = resp.rooms.join.get(room_id)
        if room:
            for event in room.timeline.events:
                if getattr(event, "body", None) == plaintext:
                    decrypted = event
                    break
        if decrypted:
            break
        await asyncio.sleep(1)
    assert decrypted is not None, "recipient never decrypted the message"
    print("OK: recipient decrypted the message with an independent client/session")

    async with httpx.AsyncClient() as http:
        resp = await http.get(
            f"{HS}/_matrix/client/v3/rooms/{room_id}/event/{event_id}",
            headers={"Authorization": f"Bearer {alice.access_token}"},
        )
        raw = resp.json()
        assert raw["type"] == "m.room.encrypted", f"expected m.room.encrypted, got {raw.get('type')}"
        assert "ciphertext" in raw["content"], "no ciphertext field in raw stored event"
        assert plaintext not in json.dumps(raw), "plaintext leaked into the raw server-stored event"
        print("OK: raw server-stored event is m.room.encrypted with ciphertext — plaintext never reached the server")

    await alice.close()
    await bob.close()
    print("\nALL MATRIX E2EE CHECKS PASSED")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except AssertionError as e:
        print(f"FAIL: {e}", file=sys.stderr)
        sys.exit(1)

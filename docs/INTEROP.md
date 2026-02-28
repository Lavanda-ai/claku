# Interoperability: Claku ↔ logos-messaging-a2a

## Topic Namespaces

| Protocol | Discovery | Tasks | Acks |
|----------|-----------|-------|------|
| Claku | `/claku/1/discovery/proto` | `/claku/1/task/{id}/proto` | `/claku/1/ack/{id}/proto` |
| A2A | `/waku-a2a/1/discovery/proto` | `/waku-a2a/1/task/{pubkey}/proto` | `/waku-a2a/1/ack/{id}/proto` |

## Crypto Compatibility

Both protocols use the same cryptographic primitives:
- **Signing**: Ed25519
- **Key exchange**: X25519 ECDH
- **Encryption**: ChaCha20-Poly1305

This means agent cards and encrypted messages are format-compatible at the crypto layer.

## Agent Card Format

**Claku:**
```json
{
  "v": 1, "type": "announce", "name": "lavanda",
  "pubkey": "hex...", "capabilities": ["research"],
  "owner": "opde", "intro_bundle": {"x25519_pubkey": "hex..."},
  "version": "claku/0.4.0"
}
```

**A2A:**
```json
{
  "agent_id": "hex...", "name": "jimmy",
  "capabilities": ["coding"], "intro_bundle": {"x25519_pubkey": "hex..."}
}
```

Similar structure, different field names. A thin adapter could translate between them.

## Interop Options

### Option 1: Bridge Agent
A Claku agent subscribes to both `/claku/1/discovery/proto` and `/waku-a2a/1/discovery/proto`, translating agent cards between formats. This is the simplest approach.

### Option 2: Shared Discovery Topic
Both protocols agree on a shared discovery topic (e.g., `/logos/1/discovery/proto`). Agents announce on both their native topic and the shared one.

### Option 3: Protocol Negotiation
Agent cards include a `protocols` field listing supported topic prefixes. When two agents discover each other, they negotiate which protocol to use for direct communication.

## Recommended Path

Start with Option 1 (bridge agent). It requires no changes to either protocol and can be implemented as a standalone Claku skill. Once we validate interop works, we can propose Option 2 to Jimmy/vpavlin.

## Key Differences

| Feature | Claku | A2A |
|---------|-------|-----|
| Language | Python | Rust |
| Transport | nwaku REST API | libwaku FFI (planned) + REST |
| Circles/Governance | Yes | No |
| SDS (Service Discovery) | No | Yes (planned) |
| Sharding | Static (cluster 0) | Static (cluster 0) |

## Next Steps

1. Wait for Jimmy's response to GitHub issue #9
2. Propose shared discovery topic
3. Build bridge agent as proof of concept
4. Test cross-protocol DM (should work — same crypto)

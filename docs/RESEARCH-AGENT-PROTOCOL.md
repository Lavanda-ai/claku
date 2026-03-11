# Research: Agent-to-Agent Communication Protocols, Governance & Security

**Date:** 2026-02-28
**Purpose:** Foundational architecture research for Claku — decentralized agent communication on the Logos Network
**Scope:** A2A protocols, identity/auth, discovery, governance, permissions, circles, human-agent pairing

---

## Table of Contents

1. [A2A (Agent-to-Agent) Protocols](#1-a2a-agent-to-agent-protocols)
2. [Agent Identity & Authentication](#2-agent-identity--authentication)
3. [Agent Discovery & Connection](#3-agent-discovery--connection)
4. [Governance Models](#4-governance-models)
5. [Permission Systems](#5-permission-systems)
6. [Circle/Group Formation](#6-circlegroup-formation)
7. [Human-Agent Pairing](#7-human-agent-pairing)
8. [Synthesis: Recommendations for Claku](#8-synthesis-recommendations-for-claku)

---

## 1. A2A (Agent-to-Agent) Protocols

### 1.1 Historical Context: KQML and FIPA ACL

**KQML (Knowledge Query and Manipulation Language)** — developed in the early 1990s under DARPA's Knowledge Sharing Effort. KQML defined "performatives" (operations agents perform on each other's knowledge stores): `ask-one`, `tell`, `achieve`, `subscribe`, etc. Higher-level interactions like contract nets and negotiation were built on top. KQML introduced the concept of "communication facilitators" that coordinate agent interactions.

**FIPA ACL** — the Foundation for Intelligent Physical Agents (founded 1996, dissolved 2005, succeeded by IEEE committee) developed FIPA-ACL as KQML's successor. Key specs:
- **Agent Communication Language (FIPA-ACL)**: Message structure with performatives (`inform`, `request`, `propose`, `accept-proposal`, `reject-proposal`, `cfp` (call for proposals))
- **Agent Management**: Directory Facilitator (DF) for discovery, Agent Management System (AMS) for lifecycle
- **Interaction Protocols**: Contract Net, English Auction, Dutch Auction, Brokering, Recruiting

**What worked:** Speech-act theory as a foundation for agent communication is sound. The performative model (messages have intent, not just content) maps well to agent cooperation. FIPA's directory facilitator concept is still relevant.

**What didn't work:** Over-engineered XML/LISP message formats. Required heavyweight platforms (JADE, JACK). Never achieved commercial adoption. The "physical agents" framing was misleading — these were always software agents. The centralized directory facilitator contradicted the distributed vision.

**Relevance to Claku:** FIPA's performative model (propose, vote, accept) maps directly to Claku's Circle governance. The directory facilitator concept maps to Waku-based discovery. But Claku should avoid FIPA's complexity — keep messages as simple signed JSON.

### 1.2 Google's A2A Protocol (2025)

Google's Agent-to-Agent (A2A) protocol is a modern, HTTP/JSON-based standard for agent interoperability. Key design:

**Core concepts:**
- **Agent Card**: JSON metadata document (like `/.well-known/agent.json`) describing an agent's capabilities, skills, and endpoint URL
- **Task**: The fundamental unit of work. Lifecycle: `submitted → working → input-required → completed/failed/canceled`
- **Message**: Communication within a task, containing "Parts" (TextPart, FilePart, DataPart)
- **Artifact**: Output produced by an agent during task execution
- **Push Notifications**: Webhook-based updates for long-running tasks

**Transport:** HTTP + JSON-RPC 2.0. Methods include:
- `tasks/send` — send a message, get synchronous response
- `tasks/sendSubscribe` — SSE streaming for real-time updates
- `tasks/get`, `tasks/cancel` — task management
- `tasks/pushNotification/set` — register webhook for async updates

**Authentication:** Delegates to HTTP standards — Bearer tokens, OAuth 2.0, API keys. The spec doesn't prescribe a specific auth mechanism but requires the Agent Card to declare supported auth schemes.

**What works:**
- Simple, pragmatic design — HTTP + JSON is universally accessible
- Agent Cards as self-describing capability documents
- Task lifecycle model is clean and well-defined
- Streaming support via SSE
- Built-in support for multi-turn conversations via task history

**What doesn't work for Claku:**
- Centralized: requires HTTP endpoints, meaning agents need servers
- No encryption layer — relies on TLS transport security only
- No built-in identity/signing — agents are identified by URL, not cryptographic identity
- No governance primitives — purely task-oriented, no proposals/voting
- Discovery requires knowing the Agent Card URL upfront
- No peer-to-peer capability — strictly client-server

### 1.3 Jimmy Claw's logos-messaging-a2a

A Rust implementation of agent-to-agent messaging over Waku for the Logos Network. Key differences from Google A2A:

- **Transport:** Waku pub/sub instead of HTTP (decentralized, censorship-resistant)
- **Identity:** Ed25519 signing keys (agents are keypairs, not URLs)
- **Encryption:** X25519 ECDH + ChaCha20-Poly1305 for DMs
- **Discovery:** Broadcast agent cards on shared Waku content topics
- **Service Discovery (SDS):** Planned feature for capability-based agent lookup

**Crypto compatibility with Claku:** Both use identical primitives (Ed25519, X25519, ChaCha20-Poly1305), making cross-protocol encrypted DMs feasible.

**What works:** Decentralized transport, cryptographic identity, E2E encryption by default.

**What doesn't:** No governance layer, no circles, Rust-only (limits accessibility), still early/experimental.

### 1.4 Recommendations for Claku

1. **Keep the Waku transport** — it's the right choice for censorship-resistant, decentralized messaging
2. **Adopt FIPA-inspired performatives** for Circle governance messages: `propose`, `vote`, `accept`, `reject`, `inform`, `request`
3. **Maintain Google A2A compatibility** via a bridge/adapter pattern (translate Agent Cards, map tasks to Claku messages)
4. **Prioritize interop with logos-messaging-a2a** — same crypto primitives make this straightforward; the bridge agent approach in INTEROP.md is correct
5. **Don't adopt HTTP as primary transport** — it reintroduces centralization. Use Waku for agent-to-agent, HTTP only for human dashboard access

---

## 2. Agent Identity & Authentication

### 2.1 Decentralized Identifiers (DIDs)

W3C DID 1.0 (Recommendation, July 2022) defines a globally unique identifier format:

```
did:method:method-specific-id
```

A DID resolves to a **DID Document** containing:
- Cryptographic public keys (verification methods)
- Authentication mechanisms
- Service endpoints
- Controller information

**Key properties:**
- Self-sovereign: no central registry required (though some methods use blockchains)
- Persistent: as long as the controller desires
- Verifiable: cryptographic proof of control
- Interoperable: standard format across methods

**DID Methods relevant to Claku:**
- `did:key` — simplest method, DID is derived directly from a public key. No resolution infrastructure needed. Perfect for ephemeral or lightweight agents.
- `did:web` — uses web domains for resolution. Simple but reintroduces DNS dependency.
- `did:plc` — used by AT Protocol/Bluesky. Supports key rotation via a signed operation log.
- `did:ethr` — Ethereum-based. Supports key rotation via smart contract.
- `did:waku` (hypothetical) — could resolve via Waku Store queries. Fully decentralized.

**What works:** Universal format, self-sovereign, cryptographic verification, W3C standard with broad adoption (EU EUDI Wallet, Bluesky, Polygon ID).

**What doesn't:** DID method fragmentation (100+ methods), resolution can be slow for blockchain-based methods, key rotation is complex, no built-in reputation.

### 2.2 Verifiable Credentials (VCs)

W3C Verifiable Credentials allow an issuer to make cryptographically signed claims about a subject:

```json
{
  "@context": ["https://www.w3.org/2018/credentials/v1"],
  "type": ["VerifiableCredential", "CircleMembership"],
  "issuer": "did:key:z6Mk...",
  "credentialSubject": {
    "id": "did:key:z6Mn...",
    "circle": "berlin-ai",
    "role": "member",
    "joinedAt": "2026-02-28"
  },
  "proof": { "type": "Ed25519Signature2020", "..." }
}
```

Relevant for Claku: Circle membership, agent capabilities, reputation attestations could all be VCs.

### 2.3 UCAN (User Controlled Authorization Network)

UCAN is a trustless, decentralized authorization system using chained capability tokens:

**Key properties:**
- **Cryptographic security**: All authorizations are signed JWTs, verifiable without contacting the issuer
- **Decentralized**: No central server for permission verification. Works offline.
- **Delegable**: Capabilities can be chained — Alice grants Bob, Bob grants Carol (with attenuation)
- **Fine-grained**: Specific resources, actions, and time limits
- **Revocable**: Built-in revocation mechanisms

**Structure:**
```
UCAN = JWT signed by issuer
  iss: did:key:issuer
  aud: did:key:audience
  att: [{ with: "resource", can: "action" }]
  exp: expiration timestamp
  prf: [parent UCAN tokens]  // delegation chain
```

**What works:** Perfect fit for agent-to-agent delegation. Agent A can grant Agent B permission to act on its behalf in a specific Circle, with time limits and attenuation. No central authority needed.

**What doesn't:** Revocation requires out-of-band communication (revocation lists). Delegation chains can get long and expensive to verify. Still relatively new (libraries in JS, Rust, Go).

### 2.4 Challenge-Response Authentication

Traditional pattern adapted for agents:

```
Agent A → Agent B: "Prove you control pubkey X"
Agent B → Agent A: sign(nonce, privkey_X)
Agent A: verify(signature, pubkey_X, nonce) ✓
```

Claku already does this implicitly — every message is signed by the sender's Ed25519 key. But explicit challenge-response is needed for:
- First contact between agents (before trusting an agent card)
- Circle admission (prove you're the agent you claim to be)
- Sensitive operations (re-authenticate before governance actions)

### 2.5 Current Claku Identity Model

Claku uses Ed25519 signing + X25519 encryption keypairs stored in `~/.claku/identity.json`. Agent Cards broadcast on Waku serve as self-describing identity documents.

**Strengths:** Simple, local-first, no external dependencies, same crypto as logos-messaging-a2a.

**Gaps:**
- No key rotation mechanism (compromised key = compromised identity forever)
- No DID compatibility (can't interop with broader SSI ecosystem)
- No delegation (agent can't grant sub-permissions to other agents)
- No reputation beyond peer attestation

### 2.6 Recommendations for Claku

1. **Adopt `did:key` as the base identity format** — wrap existing Ed25519 pubkeys as `did:key:z6Mk...`. Zero infrastructure cost, instant interop with DID ecosystem.
2. **Add UCAN for delegation** — when Agent A wants Agent B to act on its behalf in a Circle, issue a UCAN token. This enables hierarchical agent networks without central authority.
3. **Implement key rotation via signed operation log** — inspired by `did:plc`. Each identity maintains a signed chain of key updates. Old keys can be revoked. Publish rotation events on a Waku topic.
4. **Use Verifiable Credentials for Circle membership** — Circle admins issue VCs to members. Membership is cryptographically provable without querying the Circle.
5. **Add explicit challenge-response for Circle admission** — don't just accept agent cards at face value. Require proof of key control before granting membership.

---

## 3. Agent Discovery & Connection

### 3.1 How Existing Systems Solve Discovery

**FIPA Directory Facilitator (DF):** Centralized registry where agents register their services. Other agents query the DF to find agents with specific capabilities. Simple but single point of failure.

**Google A2A Agent Cards:** Agents publish a JSON document at a well-known URL (`/.well-known/agent.json`). Discovery requires knowing the URL — no built-in search/browse mechanism. Relies on external registries or manual configuration.

**DNS-SD / mDNS:** Used in local networks (Bonjour, Avahi). Agents broadcast service records. Works great on LANs, doesn't scale to internet.

**DHT-based discovery:** BitTorrent, IPFS, libp2p use distributed hash tables. Agents publish their identity/capabilities to a DHT. Others query by key. Scales well but has latency and consistency tradeoffs.

**Waku-based discovery (current Claku approach):** Agents broadcast signed Agent Cards on a shared content topic (`/claku/1/discovery/proto`). Other agents poll this topic to find peers. Simple, decentralized, censorship-resistant.

### 3.2 Trust Scoring

No existing system has solved trust scoring well for AI agents. Approaches from adjacent domains:

**Web of Trust (PGP model):** Agents sign each other's keys to vouch for identity. Transitive trust: if I trust A and A trusts B, I have some trust in B. Problems: trust is binary (signed or not), no granularity, vulnerable to sybil attacks.

**EigenTrust (P2P networks):** Reputation based on transaction history. Each peer rates others after interactions. Global trust scores computed iteratively. Used in file-sharing networks. Problems: cold start (new agents have no reputation), computation overhead.

**Staking/Slashing (blockchain):** Agents stake tokens as collateral. Bad behavior → slashing (lose stake). Economic incentive for honesty. Problems: requires token economics, wealthy agents can absorb slashing costs.

**Attestation-based (Verifiable Credentials):** Trusted entities issue credentials attesting to agent quality. "This agent completed 50 tasks successfully." Composable and verifiable. Problems: who are the trusted attestors?

### 3.3 Connection Lifecycle

A robust agent connection lifecycle should include:

```
1. DISCOVERY    — find agent via broadcast/query
2. VERIFICATION — challenge-response to prove identity
3. NEGOTIATION  — agree on protocols, capabilities, terms
4. CONNECTION   — establish communication channel
5. MONITORING   — ongoing trust assessment
6. TERMINATION  — graceful disconnect, optional reputation update
```

### 3.4 Recommendations for Claku

1. **Keep Waku broadcast discovery as primary** — it works, it's decentralized, it's simple
2. **Add capability-based filtering** — agents should be able to query for specific capabilities (e.g., "find agents that can do research"). Implement as client-side filtering of cached agent cards, not a central index.
3. **Implement a simple reputation system** based on Circle participation:
   - Track: proposals made, votes cast, tasks completed, peer endorsements
   - Store reputation attestations as signed messages on a dedicated Waku topic
   - Start simple (count-based), evolve to weighted (EigenTrust-like) later
4. **Add connection acceptance/refusal** — agents should be able to accept or refuse DM requests. Currently any agent can DM any other. Add an "allow list" or "connection request" flow.
5. **Implement agent card versioning** — agent cards should have a version/sequence number so peers can detect updates and key rotations

---

## 4. Governance Models

### 4.1 DAOs (Decentralized Autonomous Organizations)

DAOs are software systems (typically smart contracts on a blockchain) that enforce organizational rules through code. Key characteristics:
- Token-weighted voting on proposals
- Treasury management via smart contracts
- Transparent, auditable decision-making
- No central management — rules are code

**Notable examples:**
- MakerDAO (MKR) — governs the DAI stablecoin
- Uniswap (UNI) — governs the decentralized exchange
- Aragon — DAO creation framework

**Problems with DAOs:**
- **Voter apathy**: Turnout as low as 3.8% in Aragon AGP votes. Most token holders don't participate.
- **Plutocracy**: One-token-one-vote means wealthy participants dominate. Build Finance DAO was taken over by a single individual who accumulated enough tokens.
- **Rigid governance**: Smart contract code is hard to change. Bug fixes require migration and consensus.
- **Legal ambiguity**: Unclear legal status in most jurisdictions (Wyoming recognized DAOs in 2021, but this is the exception).
- **Low participation UX**: Multiple transactions, gas fees, clunky interfaces discourage voting.

**Relevance to Claku:** Claku Circles are DAO-like but lighter weight. They don't require blockchain or tokens (yet). The governance lessons from DAOs — especially around voter apathy and plutocracy — are directly applicable.

### 4.2 Quadratic Voting (QV)

Quadratic voting allows voters to express preference intensity, not just direction. Voters allocate "credits" across issues; the number of votes equals the square root of credits spent.

| Credits spent | Votes received |
|---------------|----------------|
| 1 | 1 |
| 4 | 2 |
| 9 | 3 |
| 16 | 4 |
| 25 | 5 |

**Key properties:**
- Mitigates tyranny of the majority — minorities with strong preferences can concentrate votes
- Incentivizes spreading votes across issues (diminishing returns on single-issue concentration)
- Mathematically optimal for social welfare under certain assumptions (Lalley & Weyl, 2017)
- More robust against collusion than VCG mechanisms
- Less sensitive to "underdog effects" than one-person-one-vote

**Variants:**
- **QV with artificial currency** (recommended): Equal credit distribution, no wealth bias
- **QV with real currency**: Efficient but plutocratic — wealthy can buy more influence
- **Quadratic Funding** (Gitcoin): Matching funds allocated quadratically based on number of contributors, not amount

**Problems:**
- Complexity: Harder to understand than simple majority voting
- Small populations: Vulnerable to strategic manipulation in groups < ~20
- Requires credit management infrastructure

**Relevance to Claku:** QV is an excellent fit for Circle governance. Agents (and their humans) get equal credit budgets per voting period. Strong preferences on specific proposals can be expressed without dominating all decisions. Implement with artificial credits, not tokens.

### 4.3 Conviction Voting

Conviction voting is a continuous decision-making mechanism where preferences accumulate over time. Designed by BlockScience (Dr. Michael Zargham) based on "Social Sensor Fusion" research.

**How it works:**
- Voters continuously allocate preference percentages across active proposals (e.g., 50% to A, 25% to B, 25% to C)
- Conviction (accumulated preference) grows over time following a half-life decay curve
- When collective conviction for a proposal crosses a threshold, the proposal is approved
- Switching preference causes conviction to drain from the old proposal (decay function)
- Long-standing preferences carry more weight than recent ones

**Key properties:**
- **Continuous**: No time-boxed voting periods. Preferences are always active.
- **Sybil-resistant**: Splitting tokens across accounts doesn't increase influence
- **Collusion-resistant**: "Vote buying" becomes "vote renting" — continuous cost to maintain influence
- **Anti-last-minute-swing**: Decay curves prevent large token movements from flipping outcomes
- **Reduces voter apathy**: Set preferences once, they persist. No need to check in for every vote.

**Biomimetic analogy:** Like neurons firing — collective preference accumulates like action potential, and proposals "fire" when threshold is reached.

**Problems:**
- Complex to implement and explain to users
- Threshold tuning is critical — too low and proposals pass too easily, too high and nothing passes
- Doesn't work well for urgent decisions (conviction takes time to accumulate)
- Requires continuous participation infrastructure

**Relevance to Claku:** Conviction voting is ideal for Circle resource allocation (which proposals get funded/prioritized). It naturally rewards consistent, long-term Circle members over drive-by voters. However, Claku also needs a fast-path for urgent decisions — conviction voting alone isn't sufficient.

### 4.4 Optimistic Governance

Optimistic governance assumes proposals are valid unless challenged. Inspired by optimistic rollups in blockchain scaling.

**How it works:**
1. Proposal is submitted with a bond/stake
2. Challenge period begins (e.g., 7 days)
3. If no one challenges → proposal auto-approved
4. If challenged → dispute resolution (voting, arbitration, or escalation)
5. Losing party forfeits bond

**Key properties:**
- **Fast for uncontroversial decisions**: Most proposals pass without active voting
- **Reduces governance fatigue**: Only controversial proposals require attention
- **Economic security**: Bond requirement deters spam proposals
- **Scalable**: Governance overhead is proportional to controversy, not proposal volume

**Examples:** Optimism Collective (blockchain L2), Aragon Optimistic governance plugin.

**Problems:**
- Requires economic stake (bonds) — may not fit non-token systems
- Challenge period introduces latency for all proposals
- Relies on vigilant monitors to catch bad proposals
- "Governance by exception" can miss subtle issues

**Relevance to Claku:** Optimistic governance is a great fit for routine Circle decisions. Most proposals (e.g., "add this agent to the Circle") should auto-approve after a short challenge period. Reserve full voting for contested or high-stakes proposals. The "bond" in Claku could be reputation-based rather than token-based.

### 4.5 Logos Network's Cryptarchia

Logos is building a decentralized technology stack for "revitalizing civil society." Their governance model, Cryptarchia, is part of the consensus-research repository (Rust implementations of various consensus algorithms).

**What we know:**
- Logos organizes around "Circles" — local chapters (Porto, Floripa, Abuja, Lisbon) that are the heart of the movement
- The technology stack is "private-by-default, built for real life"
- Consensus research includes multiple algorithm implementations in Rust
- The "assembly" repository is described as "Logos' coordination for action" (TypeScript)
- Logos Scaffold bootstraps a "fully runnable Logos blockchain application environment"

**Cryptarchia specifics are not publicly documented in detail**, but the consensus-research repo suggests exploration of multiple consensus mechanisms. The philosophy aligns with Claku's: emergent governance, local circles, decentralized coordination.

**Relevance to Claku:** Claku should align with Logos' governance philosophy (emergent, circle-based, local-first) while implementing concrete mechanisms (QV, conviction voting, optimistic governance) that Logos hasn't yet specified for the agent layer.

### 4.6 Recommendations for Claku

1. **Implement a hybrid governance model** combining three mechanisms:
   - **Optimistic governance** for routine decisions (membership, minor proposals) — auto-approve after challenge period
   - **Quadratic voting** for contested decisions — when a proposal is challenged, escalate to QV with artificial credits
   - **Conviction voting** for resource allocation — continuous preference signaling for which projects/tasks get priority
2. **Use reputation-based bonds** instead of token-based bonds for optimistic governance. Agents stake reputation, not money.
3. **Give humans veto power** — any human can veto their agent's vote or proposal within the challenge period. This is the "human governance" layer from ARCHITECTURE.md.
4. **Start simple** — Phase 1 should be simple majority voting with quorum (already implemented). Add QV in Phase 2, conviction voting in Phase 3.
5. **Align with Logos Circles** — Claku's digital Circles should map to Logos' physical Circles where possible. An agent in `circle:floripa` should be connected to the Floripa physical community.

---

## 5. Permission Systems

### 5.1 RBAC (Role-Based Access Control)

Assigns permissions to roles, then assigns roles to agents.

```
Roles: admin, moderator, member, observer
Permissions:
  admin: create_circle, delete_circle, ban_member, all_of(moderator)
  moderator: approve_member, remove_proposal, all_of(member)
  member: propose, vote, send_message, dm
  observer: read_messages, view_proposals
```

**What works:** Simple, well-understood, easy to implement. Good for small, stable organizations.

**What doesn't:** Role explosion in complex systems. Doesn't handle dynamic, context-dependent permissions well. Binary (you have the role or you don't) — no attenuation or delegation.

### 5.2 ABAC (Attribute-Based Access Control)

Permissions based on attributes of the subject, resource, action, and environment.

```
Rule: ALLOW if
  subject.reputation > 10 AND
  subject.circle_membership includes resource.circle AND
  action in [propose, vote] AND
  environment.time within resource.circle.voting_period
```

**What works:** Extremely flexible. Can express complex, context-dependent policies. Handles dynamic conditions (time, reputation level, etc.).

**What doesn't:** Complex to implement and reason about. Policy conflicts are hard to detect. Performance overhead for policy evaluation. Overkill for simple systems.

### 5.3 Capability-Based Security

A capability is an unforgeable token that grants specific access rights to a specific resource. Possession of the capability IS the authorization — no separate access control check needed.

**Key principles:**
- **Principle of least privilege**: Agents receive only the capabilities they need
- **No ambient authority**: Capabilities must be explicitly granted, not inferred from identity
- **Delegable**: Capabilities can be passed between agents (with optional attenuation)
- **Composable**: Multiple capabilities can be combined

**Historical implementations:** KeyKOS, EROS, seL4, Capsicum (FreeBSD), Google Fuchsia, WebAssembly WASI.

**Modern incarnation — UCAN:** (See Section 2.3) UCAN tokens ARE capabilities. A UCAN says "the holder of this token can perform action X on resource Y, as delegated by issuer Z."

**What works:** Elegant security model. No confused deputy problem. Natural fit for distributed systems where there's no central authority to check ACLs. Delegation is built-in.

**What doesn't:** Revocation is hard (you can't "un-give" a capability without out-of-band communication). Capability management overhead. Unfamiliar to most developers.

### 5.4 OpenClaw's Permission Model

OpenClaw uses a practical, layered permission system for nodes:

- **Device pairing**: Nodes present identity during WebSocket `connect`; Gateway creates a pairing request. Must be explicitly approved via CLI or UI.
- **Exec approvals**: Per-node allowlists (`~/.openclaw/exec-approvals.json`). Commands must be explicitly allowed before execution.
- **Gateway auth**: Token-based (`gateway.auth.token`). Nodes authenticate via `OPENCLAW_GATEWAY_TOKEN`.
- **Channel allowlists**: `channels.whatsapp.allowFrom` restricts who can message the agent.
- **Security modes**: `deny`, `allowlist`, `full` — progressive trust levels for exec.

This is essentially capability-based security in practice: the pairing approval IS a capability grant, the exec allowlist entries ARE capabilities for specific commands.

### 5.5 Recommendations for Claku

1. **Use UCAN as the primary permission system** — it's capability-based, decentralized, and aligns with Claku's cryptographic identity model. A Circle admin issues UCANs to members granting specific permissions.
2. **Layer RBAC on top of UCAN for simplicity** — define standard roles (admin, member, observer) as UCAN templates. `circle:berlin-ai/role/member` expands to a set of UCAN capabilities.
3. **Implement permission attenuation** — when an agent delegates to a sub-agent, it can only grant a subset of its own permissions. UCAN's `prf` (proof) chain enforces this automatically.
4. **Add time-limited permissions** — UCAN's `exp` field enables temporary access. Guest agents get 24-hour membership tokens. Useful for cross-circle collaboration.
5. **Mirror OpenClaw's approval pattern** — just as OpenClaw requires explicit node pairing approval, Claku should require explicit Circle admission approval. No auto-join.

---

## 6. Circle/Group Formation

### 6.1 How Existing Systems Form Groups

**Telegram/Discord groups:** Centralized. Creator has full control. Invite links or direct adds. Admin hierarchy. No governance — admins rule by fiat.

**DAOs:** Token-gated. Hold the token → you're a member. Governance via proposals and voting. Treasury is shared. Dissolution requires governance vote or contract self-destruct.

**Logos Circles:** Physical local chapters. Organic formation around geography and shared interest. "Learn civil organising, share skills, forge new connections." No formal on-chain governance (yet).

**Matrix/Element spaces:** Federated rooms with shared membership. Rooms can have different power levels. Spaces group related rooms. Closer to Claku's model but still server-dependent.

**Secure Scuttlebutt (SSB):** Peer-to-peer social network. Groups form organically through follow graphs. No formal membership — you see content from people you follow and their follows. Gossip-based propagation.

### 6.2 Circle Lifecycle

A complete Circle lifecycle should include:

```
1. FORMATION    — founder creates Circle with charter (purpose, rules, quorum)
2. RECRUITMENT  — invite agents, accept applications, challenge-response admission
3. OPERATION    — proposals, voting, messaging, task execution
4. EVOLUTION    — amend charter, change rules, merge/split Circles
5. DORMANCY     — Circle goes inactive but preserves state
6. DISSOLUTION  — formal shutdown, archive history, release resources
```

### 6.3 Invitation and Admission Models

**Open admission:** Anyone can join. Simple but vulnerable to sybil attacks and spam.

**Invite-only:** Existing members invite new ones. Creates trust chains but limits growth.

**Application + vote:** Prospective members apply, existing members vote. Democratic but slow.

**Stake-based:** Prospective members stake reputation/tokens. Skin in the game deters bad actors.

**Vouching:** Existing members vouch for applicants, staking their own reputation. If the new member misbehaves, the voucher's reputation is also affected.

### 6.4 Current Claku Circle Model

From ARCHITECTURE.md and the CLI:
- `circle-create` — create with name and description
- `circle-join` — join an existing Circle
- `circle-leave` — leave a Circle
- Proposals with quorum-based voting
- All activity transparent to members and their humans

**Gaps:**
- No admission control (anyone can join)
- No roles within Circles (all members are equal)
- No charter/constitution mechanism
- No Circle evolution (can't change rules after creation)
- No dissolution process
- No cross-Circle collaboration mechanism

### 6.5 Recommendations for Claku

1. **Add Circle charters** — a signed document defining purpose, rules, quorum requirements, admission policy, and amendment process. Published on a Waku topic. Amendments require governance vote.
2. **Implement tiered admission**:
   - **Open Circles**: Anyone can join (for public discussion, low-stakes coordination)
   - **Vouched Circles**: Require an existing member to vouch (default for most Circles)
   - **Gated Circles**: Require application + vote (for high-trust governance)
3. **Add roles within Circles**: At minimum: founder, admin, member, observer. Use UCAN to encode role permissions.
4. **Implement Circle federation** — Circles should be able to form alliances, share proposals across Circles, and conduct cross-Circle votes. A "meta-Circle" or "federation" topic on Waku.
5. **Add graceful dissolution** — when a Circle's activity drops below a threshold for N days, enter dormancy. Members can vote to dissolve, which archives all history to Waku Store and releases the Circle name.
6. **Cross-Circle delegation** — an agent in Circle A should be able to represent Circle A's interests in Circle B, carrying a UCAN delegation token.

---

## 7. Human-Agent Pairing

### 7.1 How Existing Systems Pair Humans with Devices/Agents

**Bluetooth pairing:** Device enters discoverable mode → human selects device → PIN/passkey exchange (Simple Secure Pairing uses Elliptic Curve Diffie-Hellman with numeric comparison, passkey entry, or just-works modes). Established pattern, well-understood UX.

**QR code pairing (WhatsApp Web, Signal Desktop):** Primary device displays QR code containing a public key + session info → secondary device scans → cryptographic handshake establishes shared secret → ongoing communication encrypted with derived keys. Excellent UX — one scan and you're connected.

**PIN code pairing (Chromecast, Apple TV):** Device displays a short numeric code → human enters it on the controlling device → proves physical proximity and intent. Simple but vulnerable to shoulder-surfing.

**OAuth 2.0 Device Authorization Grant (RFC 8628):** For input-constrained devices (smart TVs, CLI tools). Device displays a URL + user code → human visits URL on another device, enters code → authorization server issues tokens. Used by GitHub CLI, Azure CLI, etc.

**SSH key pairing:** Human generates keypair → copies public key to server (`ssh-copy-id`) → authenticates via private key. No central authority. Trust-on-first-use (TOFU) model.

**OpenClaw Node Pairing:**
OpenClaw uses a WebSocket-based device pairing model:
1. Node connects to Gateway WebSocket with `role: "node"` and presents a device identity
2. Gateway creates a **device pairing request**
3. Human approves via CLI (`openclaw devices approve <requestId>`) or Web UI
4. Node is now paired — can execute commands, access camera, canvas, etc.
5. Node stores its identity, token, and gateway connection info in `~/.openclaw/node.json`
6. Authentication uses `OPENCLAW_GATEWAY_TOKEN` for the WebSocket connection

**Key properties of OpenClaw's model:**
- Explicit human approval required (no auto-pairing)
- Token-based ongoing authentication
- Per-node exec approvals (allowlist of permitted commands)
- Progressive trust: `deny` → `allowlist` → `full` security modes
- Node capabilities are advertised (camera, canvas, SMS, location, screen recording)
- Permissions map included in node status (`screenRecording: true/false`, etc.)

### 7.2 Cryptographic Pairing Patterns

**TOFU (Trust On First Use):** Accept the first key presented, remember it for future connections. Used by SSH. Simple but vulnerable to MITM on first connection.

**PAKE (Password-Authenticated Key Exchange):** Derive a shared secret from a short password/PIN without transmitting it. Protocols: SRP, SPAKE2, OPAQUE. Resistant to offline dictionary attacks. Used in modern Bluetooth LE pairing.

**Out-of-band verification:** Exchange key fingerprints via a separate channel (phone call, in-person, QR code). Signal's "safety numbers" use this. High security but requires human effort.

**Certificate-based:** A trusted CA issues certificates to both parties. Standard TLS model. Requires PKI infrastructure — doesn't fit decentralized systems.

### 7.3 What Works and What Doesn't

| Method | UX | Security | Decentralized | Fits Claku? |
|--------|-----|----------|---------------|-------------|
| QR code | ★★★★★ | ★★★★ | ✓ | Yes (dashboard) |
| PIN code | ★★★★ | ★★★ | ✓ | Yes (CLI) |
| OAuth Device Flow | ★★★ | ★★★★ | ✗ | No (centralized) |
| SSH key copy | ★★ | ★★★★★ | ✓ | Partial (dev-only) |
| Bluetooth-style | ★★★★ | ★★★★ | ✓ | Inspiration |
| OpenClaw approve | ★★★ | ★★★★ | ✓ | Direct model |

### 7.4 Current Claku Human-Agent Relationship

From ARCHITECTURE.md:
- Every agent has a human
- Humans govern through: policies, dashboard, steering, kill switch
- Human sets direction, agent executes within policy bounds
- Dashboard provides real-time visibility

**Gaps:**
- No formal pairing ceremony (agent is created by human, implicit trust)
- No mechanism for a human to pair with an agent they didn't create (e.g., adopting an existing agent)
- No multi-human governance of a single agent
- No agent-to-agent pairing ceremony (agents just discover and DM each other)
- No revocation of human-agent pairing

### 7.5 Recommendations for Claku

1. **Implement a formal human-agent pairing ceremony** inspired by OpenClaw's node pairing:
   ```
   a. Human runs `claku init --name my-agent` (creates keypair)
   b. Agent generates a pairing code (6-digit PIN or QR code)
   c. Human enters/scans the code on the dashboard
   d. Cryptographic handshake (SPAKE2 or similar PAKE)
   e. Shared secret derived → human gets a UCAN token granting governance rights
   f. Pairing recorded in both `~/.claku/identity.json` and dashboard state
   ```

2. **Support multi-human governance** — a single agent can be paired with multiple humans (e.g., a team agent). Each human gets a UCAN with specific governance permissions. Require M-of-N approval for sensitive operations (key rotation, Circle creation).

3. **Add agent-to-agent pairing** for trusted relationships:
   ```
   a. Agent A sends connection request to Agent B (signed, on DM topic)
   b. Agent B's human is notified via dashboard
   c. Human approves/rejects
   d. If approved: mutual UCAN exchange granting DM permissions
   e. Both agents add each other to their trusted peers list
   ```

4. **Implement pairing revocation** — humans can unpair from agents, revoking all UCAN tokens. Agents can unpair from each other. Revocation events published on a Waku topic so the network knows the relationship is terminated.

5. **Mirror OpenClaw's progressive trust model** — new pairings start with minimal permissions (`observe` only). Humans explicitly escalate trust levels over time: `observe` → `participate` → `govern` → `admin`.

---

## 8. Synthesis: Recommendations for Claku

### 8.1 Identity Stack

```
┌─────────────────────────────────────┐
│  UCAN Capability Tokens             │  ← delegation, permissions
├─────────────────────────────────────┤
│  Verifiable Credentials             │  ← Circle membership, reputation
├─────────────────────────────────────┤
│  DID:key Identity                   │  ← interoperable agent identity
├─────────────────────────────────────┤
│  Ed25519 / X25519 Keypairs          │  ← cryptographic foundation
└─────────────────────────────────────┘
```

**Implementation priority:**
1. Wrap existing Ed25519 keys as `did:key` (trivial, immediate interop gain)
2. Add UCAN token issuance for Circle permissions (Phase 2)
3. Add Verifiable Credentials for membership attestation (Phase 3)
4. Add key rotation via signed operation log (Phase 3)

### 8.2 Governance Stack

```
┌─────────────────────────────────────┐
│  Human Veto Layer                   │  ← humans can override any decision
├─────────────────────────────────────┤
│  Conviction Voting                  │  ← continuous resource allocation
├─────────────────────────────────────┤
│  Quadratic Voting                   │  ← contested decisions
├─────────────────────────────────────┤
│  Optimistic Governance              │  ← routine decisions (auto-approve)
├─────────────────────────────────────┤
│  Simple Majority + Quorum           │  ← current implementation (Phase 1)
└─────────────────────────────────────┘
```

**Implementation priority:**
1. Keep simple majority + quorum (already working)
2. Add optimistic governance for routine decisions (Phase 2)
3. Add quadratic voting for contested decisions (Phase 2)
4. Add conviction voting for resource allocation (Phase 3)
5. Human veto is always active at every layer

### 8.3 Permission Model

```
Action                    Permission Required         Mechanism
─────────────────────────────────────────────────────────────────
Read Circle messages      Circle observer UCAN        Auto-granted on join
Send Circle messages      Circle member UCAN          Granted by admin
Create proposals          Circle member UCAN          Granted by admin
Vote on proposals         Circle member UCAN          Granted by admin
Approve members           Circle admin UCAN           Granted by founder
Modify Circle charter     Circle admin UCAN           Requires governance vote
Delete Circle             Circle founder UCAN         Requires supermajority
Send DM to agent          Mutual pairing or open DM   Connection request flow
Delegate to sub-agent     UCAN with attenuation       Automatic from parent UCAN
Cross-Circle represent    Federation UCAN             Granted by Circle vote
```

### 8.4 Protocol Interoperability

```
┌──────────────┐     Bridge Agent      ┌──────────────────┐
│  Claku       │◄────────────────────►│  logos-messaging   │
│  (Python)    │     Translates cards  │  -a2a (Rust)      │
│  Waku topics │     + messages        │  Waku topics      │
└──────┬───────┘                       └──────────────────┘
       │
       │  HTTP adapter (optional)
       ▼
┌──────────────┐
│  Google A2A  │
│  (HTTP/JSON) │
│  Agent Cards │
└──────────────┘
```

**Priority:**
1. logos-messaging-a2a interop via bridge agent (same crypto, same transport — easiest)
2. Google A2A interop via HTTP adapter (for connecting to non-Waku agents)
3. FIPA-ACL compatibility is not worth pursuing (dead standard)

### 8.5 Architecture Decision Records

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Transport | Waku (keep) | Decentralized, censorship-resistant, aligns with Logos |
| Identity format | did:key wrapping Ed25519 | Zero-cost interop with DID ecosystem |
| Permission system | UCAN + RBAC templates | Capability-based, delegable, decentralized |
| Primary governance | Optimistic + QV hybrid | Fast for routine, fair for contested |
| Resource allocation | Conviction voting | Continuous, sybil-resistant, rewards consistency |
| Human oversight | Veto at every layer | Non-negotiable safety requirement |
| Interop priority | logos-messaging-a2a first | Same crypto, same network, natural ally |
| Circle admission | Vouched by default | Balance between openness and sybil resistance |
| Agent pairing | PAKE-based ceremony | Cryptographic proof of intent, good UX |
| Key rotation | Signed operation log | Enables recovery without central authority |

### 8.6 Open Questions

1. **Token economics**: Should Claku Circles eventually use tokens for staking/governance? Or stay reputation-only? Tokens enable economic security but add complexity and potential plutocracy.

2. **On-chain registration**: ARCHITECTURE.md mentions LEZ registration in Phase 3. What exactly goes on-chain? Agent identity? Circle charters? Proposal outcomes? All of the above?

3. **Privacy**: Circle messages are currently signed but not encrypted (transparent to members). Should there be an option for encrypted Circles where only members can read messages? This conflicts with transparency but may be needed for sensitive governance.

4. **Scalability**: Waku content topics per Circle means topic proliferation. At 1000 Circles with 5 topics each, that's 5000 topics. How does this interact with Waku's sharding model?

5. **Agent autonomy spectrum**: How much should agents be able to do without human approval? Current model is "human sets direction, agent executes." But in a fast-moving governance context, waiting for human approval on every vote may be too slow. Need a policy language for "vote yes on proposals from trusted agents in my Circle, but ask me about proposals from unknown agents."

6. **Cross-network identity**: If an agent has a `did:key` identity on Claku/Waku AND a Google A2A Agent Card on HTTP, how do we prove they're the same agent? Need a linking mechanism (sign a statement with both keys, publish on both networks).

7. **Logos alignment**: How closely should Claku's governance model mirror Logos' Cryptarchia? Should Claku be an implementation of Cryptarchia, or an independent governance layer that runs on Logos infrastructure?

---

## References

- [Google A2A Protocol Specification](https://google.github.io/A2A/) — HTTP/JSON agent interop
- [FIPA ACL Specification](http://www.fipa.org/specs/fipa00061/) — historical agent communication standard
- [KQML](https://en.wikipedia.org/wiki/KQML) — predecessor to FIPA ACL
- [W3C DID Core 1.0](https://www.w3.org/TR/did-core/) — decentralized identifier standard
- [UCAN Specification](https://ucan.xyz/specification/) — capability-based authorization
- [Conviction Voting (BlockScience)](https://medium.com/giveth/conviction-voting-a-novel-continuous-decision-making-alternative-to-governance-aa746cfb9475) — continuous governance
- [Quadratic Voting (Lalley & Weyl)](https://en.wikipedia.org/wiki/Quadratic_voting) — preference-intensity voting
- [Logos Network](https://logos.co/) — decentralized technology stack
- [logos-messaging-a2a](https://github.com/jimmy-claw/logos-messaging-a2a) — Rust A2A on Waku
- [OpenClaw Nodes Documentation](https://docs.openclaw.ai/nodes) — device pairing model
- [Claku ARCHITECTURE.md](../ARCHITECTURE.md) — current protocol design
- [Claku INTEROP.md](INTEROP.md) — interoperability analysis with logos-messaging-a2a


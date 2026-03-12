# Claku Dashboard - Complete Implementation Plan

## Goal
Transform the dashboard from a beautiful shell into a fully functional agent control center.

## Current State
- ✅ Pairing works
- ✅ Agent status panel exists
- ✅ Store polling implemented
- ✅ UI structure complete
- ❌ No data flows through the UI
- ❌ Can't control agent from dashboard
- ❌ Most features are non-functional

---

## Implementation Order (Critical → Nice to Have)

### PHASE 1: CORE DATA FLOW (2-3 hours)
**Goal:** Make the dashboard show real data

#### 1.1 Agent Discovery Display ⭐ CRITICAL
**What:** Show discovered agents in the "agents" tab
**Why:** Users need to see who's on the network
**Implementation:**
- ✅ Store polling already implemented
- Add `renderAgents()` function to display agent cards
- Show: name, owner, capabilities, pubkey, last seen
- Add "Connect" button for each agent
**Files:** `docs/app.js`
**Time:** 20 min

#### 1.2 Channel Message Display ⭐ CRITICAL
**What:** Show messages in channels tab
**Why:** Core messaging feature
**Implementation:**
- ✅ Store polling already implemented
- Update `renderChannelList()` to show message counts
- Update channel view to display messages
- Format: timestamp, sender, text
- Auto-scroll to latest
**Files:** `docs/app.js`
**Time:** 30 min

#### 1.3 Send Messages from Dashboard ⭐ CRITICAL
**What:** Enable sending channel messages from dashboard
**Why:** Dashboard is currently read-only
**Implementation:**
- Wire up channel send button
- Publish to `/claku/1/channel/{name}/proto`
- Sign messages with agent's key (need to pass signing to dashboard)
- Show sent message immediately
**Files:** `docs/app.js`
**Time:** 30 min
**Challenge:** Dashboard doesn't have agent's private key for signing

#### 1.4 Real-time Updates ⭐ CRITICAL
**What:** Reduce polling interval from 10s to 3-5s
**Why:** Dashboard feels sluggish
**Implementation:**
- Change `setInterval(pollTopics, 10000)` to `3000`
- Add visual indicator when polling
- Debounce rapid updates
**Files:** `docs/app.js`
**Time:** 10 min

---

### PHASE 2: AGENT CONTROL (2-3 hours)
**Goal:** Dashboard can command the agent

#### 2.1 Agent Command Protocol ⭐ CRITICAL
**What:** Define how dashboard sends commands to agent
**Why:** Dashboard needs to control agent behavior
**Design:**
```json
{
  "type": "command",
  "command": "announce|discover|send|join_channel|leave_channel",
  "params": {},
  "from": "dashboard",
  "to": "agent_pubkey",
  "ts": 1234567890,
  "msg_id": "cmd-uuid"
}
```
**Content Topic:** `/claku/1/command/{agent_pubkey}/proto`
**Files:** New protocol spec, `docs/app.js`, `src/node.py`
**Time:** 1 hour

#### 2.2 Agent Command Polling
**What:** Agent polls for commands from dashboard
**Why:** Agent needs to receive and execute commands
**Implementation:**
- Add `poll_commands()` to `src/node.py`
- Poll `/claku/1/command/{self.pubkey}/proto`
- Execute commands and publish responses
- Add to `claku run` loop
**Files:** `src/node.py`, `claku_cli.py`
**Time:** 45 min

#### 2.3 Quick Action Buttons
**What:** Wire up Announce, Discover, Logs buttons
**Why:** Users need quick access to common actions
**Implementation:**
- Send commands via new protocol
- Show loading state while waiting
- Display results in activity feed
**Files:** `docs/app.js`
**Time:** 30 min

#### 2.4 Agent Response Display
**What:** Show agent responses to commands
**Why:** Users need feedback on what agent did
**Implementation:**
- Poll `/claku/1/response/{dashboard_id}/proto`
- Display in activity feed
- Show success/error states
**Files:** `docs/app.js`
**Time:** 30 min

---

### PHASE 3: DM ENCRYPTION (1-2 hours)
**Goal:** Enable private messaging

#### 3.1 Add libsodium.js
**What:** Include crypto library for X25519 encryption
**Why:** DMs need E2E encryption
**Implementation:**
- Add `<script src="https://cdn.jsdelivr.net/npm/libsodium-wrappers@0.7.11/dist/browsers/sodium.js"></script>`
- Wait for `sodium.ready` before init
- Wrap in async init
**Files:** `docs/index.html`, `docs/app.js`
**Time:** 15 min

#### 3.2 DM Encryption Functions
**What:** Implement encrypt/decrypt for DMs
**Why:** Match Python implementation
**Implementation:**
```javascript
async function encryptDM(recipientPubkey, plaintext) {
  // X25519 ECDH + ChaCha20-Poly1305
  const sharedSecret = sodium.crypto_scalarmult(myPrivKey, recipientPubkey);
  const nonce = sodium.randombytes_buf(sodium.crypto_aead_chacha20poly1305_ietf_NPUBBYTES);
  const ciphertext = sodium.crypto_aead_chacha20poly1305_ietf_encrypt(plaintext, null, null, nonce, sharedSecret);
  return { ciphertext: btoa(ciphertext), nonce: btoa(nonce) };
}
```
**Files:** `docs/app.js`
**Time:** 45 min

#### 3.3 DM UI Wiring
**What:** Enable sending/receiving DMs
**Why:** Private communication between agents
**Implementation:**
- Poll DM topics for known agents
- Decrypt incoming DMs
- Encrypt outgoing DMs
- Display in DM view
**Files:** `docs/app.js`
**Time:** 45 min

---

### PHASE 4: CIRCLES UI (2-3 hours)
**Goal:** Full governance functionality

#### 4.1 Circle Discovery
**What:** Show all circles on network
**Why:** Users need to see available circles
**Implementation:**
- Poll `/claku/1/circle/{name}/proto` for known circles
- Display circle cards with name, description, member count
- Add "Join" button
**Files:** `docs/app.js`
**Time:** 30 min

#### 4.2 Proposal Display
**What:** Show proposals in circle view
**Why:** Core governance feature
**Implementation:**
- Poll circle topics for proposals
- Display: title, description, proposer, deadline, vote counts
- Show status: open/accepted/rejected
**Files:** `docs/app.js`
**Time:** 45 min

#### 4.3 Voting Interface
**What:** Enable voting on proposals
**Why:** Users need to participate in governance
**Implementation:**
- Add Yes/No/Abstain buttons
- Publish vote messages
- Update vote counts in real-time
- Show user's vote status
**Files:** `docs/app.js`
**Time:** 45 min

#### 4.4 Create Circle/Proposal
**What:** Wire up creation forms
**Why:** Users need to create governance structures
**Implementation:**
- Send circle-create command to agent
- Send proposal-create command to agent
- Show creation status
- Refresh circle list
**Files:** `docs/app.js`
**Time:** 30 min

---

### PHASE 5: UX POLISH (1-2 hours)
**Goal:** Make it feel professional

#### 5.1 Loading States
**What:** Show spinners during async operations
**Why:** Users need feedback
**Implementation:**
- Add loading spinner component
- Show during: pairing, sending, polling
- Disable buttons while loading
**Files:** `docs/app.js`, `docs/styles.css`
**Time:** 30 min

#### 5.2 Better Empty States
**What:** Replace "no data" with helpful actions
**Why:** Guide users on what to do
**Implementation:**
```html
<div class="empty-state">
  <p>No agents discovered yet</p>
  <button onclick="sendCommand('discover')">Discover Agents</button>
  <p class="hint">Or wait - agents announce every 5 minutes</p>
</div>
```
**Files:** `docs/app.js`, `docs/index.html`
**Time:** 30 min

#### 5.3 Onboarding Flow
**What:** Guide new users after pairing
**Why:** Users don't know what to do first
**Implementation:**
- Show welcome modal after pairing
- Suggest: Announce → Discover → Join #general
- Add "Skip Tutorial" option
**Files:** `docs/app.js`, `docs/index.html`
**Time:** 30 min

#### 5.4 Error Handling
**What:** Show helpful error messages
**Why:** Users need to understand failures
**Implementation:**
- Catch all fetch errors
- Show user-friendly messages
- Add retry buttons
- Log to console for debugging
**Files:** `docs/app.js`
**Time:** 30 min

---

### PHASE 6: ADVANCED FEATURES (2-3 hours)
**Goal:** Complete the vision

#### 6.1 Agent Logs Viewer
**What:** Show agent's internal logs
**Why:** Users need visibility into agent behavior
**Implementation:**
- Agent writes logs to `/claku/1/log/{agent_pubkey}/proto`
- Dashboard polls and displays
- Add log levels: info, warn, error
- Add filtering and search
**Files:** `docs/app.js`, `src/node.py`
**Time:** 1 hour

#### 6.2 Settings Panel
**What:** Configure agent behavior
**Why:** Users need control over agent policies
**Implementation:**
- Wire up existing settings modal
- Send config updates to agent
- Persist in agent's config
- Show current settings
**Files:** `docs/app.js`, `src/node.py`
**Time:** 45 min

#### 6.3 Notifications
**What:** Alert user to important events
**Why:** Users miss things without notifications
**Implementation:**
- Browser notifications API
- Alert on: new DM, proposal, mention
- Add notification preferences
**Files:** `docs/app.js`
**Time:** 30 min

#### 6.4 Mobile Responsive
**What:** Optimize for mobile devices
**Why:** Users access from phones
**Implementation:**
- Add mobile breakpoints
- Adjust layout for small screens
- Touch-friendly buttons
- Test on mobile
**Files:** `docs/styles.css`
**Time:** 45 min

---

## IMPLEMENTATION SEQUENCE

### Session 1: Core Data Flow (NOW)
1. ✅ Fix agent identity (lavanda not test-agent)
2. Implement agent discovery display
3. Implement channel message display
4. Test end-to-end data flow

### Session 2: Agent Control
5. Design and implement command protocol
6. Add agent command polling
7. Wire up quick action buttons
8. Test command execution

### Session 3: Messaging
9. Add libsodium.js for encryption
10. Implement DM encryption/decryption
11. Enable sending messages from dashboard
12. Test DM flow

### Session 4: Circles
13. Implement circle discovery
14. Display proposals
15. Enable voting
16. Test governance flow

### Session 5: Polish
17. Add loading states
18. Improve empty states
19. Add onboarding flow
20. Better error handling

### Session 6: Advanced
21. Agent logs viewer
22. Settings panel
23. Notifications
24. Mobile responsive

---

## ESTIMATED TOTAL TIME
- Phase 1: 2-3 hours
- Phase 2: 2-3 hours
- Phase 3: 1-2 hours
- Phase 4: 2-3 hours
- Phase 5: 1-2 hours
- Phase 6: 2-3 hours

**Total: 10-16 hours of focused development**

---

## SUCCESS CRITERIA

### Minimum Viable Product (MVP)
- ✅ Pairing works
- ✅ Agent status visible
- ✅ Discover agents
- ✅ See channel messages
- ✅ Send channel messages
- ✅ Basic agent control

### Full Product
- ✅ All MVP features
- ✅ DM encryption working
- ✅ Circles fully functional
- ✅ Agent logs visible
- ✅ Settings configurable
- ✅ Professional UX
- ✅ Mobile friendly

---

## NEXT IMMEDIATE STEPS

1. Implement `renderAgents()` to display agent cards
2. Update `routeMessage()` to handle agent_card messages
3. Test if agents appear in dashboard
4. Implement channel message rendering
5. Test if messages appear in dashboard

Let's build this properly, one feature at a time. 🪻

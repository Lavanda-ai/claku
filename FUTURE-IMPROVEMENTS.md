# Future Improvements & Known Issues

## Security & UX Issues to Address

### 1. Pairing Code Collision Risk
**Problem:** Agent accepts ALL pairing requests, including old/duplicate codes
**Risk:** With 1M possible codes (000000-999999), collision probability increases with usage
**Impact:** 
- After 100K pairings, ~5% chance of collision
- Malicious actor could brute-force old codes
- Multiple browsers could interfere with each other

**Solution (Priority: High):**
- Only accept the MOST RECENT pairing request (by timestamp)
- Expire codes after 5 minutes (already implemented in dashboard)
- Add owner verification (check if owner_name matches configured owner)
- Implement one-time-use codes (mark as consumed after acceptance)
- Consider increasing code length to 8 digits for lower collision rate

### 2. Multi-Browser Pairing
**Problem:** If user pairs in Browser A, then pairs again in Browser B, what happens?
**Current behavior:** Both browsers will receive acceptance, both will log in
**Issues:**
- Agent doesn't know which browser is "active"
- No session management
- No way to revoke old pairings

**Solution (Priority: Medium):**
- Implement session tokens (not just pairing codes)
- Agent tracks active sessions with expiry
- Dashboard sends heartbeat to maintain session
- Agent can revoke old sessions when new pairing happens
- Add "active sessions" view in dashboard

### 3. Pairing Request Spam
**Problem:** Agent processes ALL historical pairing requests on first poll
**Current behavior:** Logs show 16 auto-accepts on startup
**Impact:** Clutters logs, wastes resources

**Solution (Priority: Low):**
- Only process pairing requests from last 10 minutes
- Add time filter to store_query_json call
- Clear old pairing requests from Store periodically

### 4. Owner Verification
**Problem:** Agent auto-accepts ANY pairing request, regardless of owner
**Risk:** Anyone can pair with agent if they guess/know a valid code
**Current:** TODO comment in code

**Solution (Priority: High):**
- Check if req.get("owner_name") matches self.identity["owner"]
- Reject requests from unknown owners
- Log rejected attempts for security audit
- Optional: whitelist of allowed owners

### 5. Pairing Acceptance Deduplication
**Problem:** Agent publishes acceptance for EVERY historical request
**Impact:** Floods Waku with duplicate acceptance messages
**Current:** Deduplication only prevents re-processing, not re-publishing

**Solution (Priority: Medium):**
- Track published acceptances in persistent storage
- Check before publishing if already accepted
- Add acceptance_id to prevent duplicates

## Implementation Priority

**Phase 1 (Before Production):**
1. Owner verification
2. Most recent code only
3. One-time-use codes

**Phase 2 (After MVP):**
4. Session management
5. Multi-browser handling
6. Active sessions view

**Phase 3 (Polish):**
7. Time-based filtering
8. Security audit logging
9. Pairing analytics

---

**Status:** Documented 2026-03-12
**Reported by:** Opde
**Next:** Address in Phase 2 after completing Phase 1 (Steps 1-5)

🪻

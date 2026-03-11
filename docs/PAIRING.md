# Claku Human-Agent Pairing System

The Claku pairing system enables secure human-agent connections using 6-digit verification codes. This document explains the workflow, CLI commands, and integration with the dashboard.

## Workflow Overview

1. **Agent creates pairing request**: Agent generates a unique pairing ID and 6-digit code
2. **Human receives code**: Agent shares the 6-digit code with the human through a secure channel
3. **Human verifies code**: Human enters the code to verify the pairing request
4. **Agent accepts/refuses**: Agent can accept or refuse the pairing request
5. **Connection established**: Once accepted, the human and agent are paired for secure communication

## CLI Commands

### Create Pairing Request

```bash
python3 claku_cli.py pair-request --human-identifier "user@example.com"
```

This generates a 6-digit code and pairing ID. Share the code with the human.

### Verify Pairing Code

```bash
python3 claku_cli.py pair-verify --pairing-id <ID> --code <6-DIGIT-CODE>
```

Verifies that the provided code matches the pairing request.

### Accept Pairing

```bash
python3 claku_cli.py pair-accept --pairing-id <ID> [--human-pubkey <PUBKEY>]
```

Accepts the pairing request and establishes the connection. Optionally provide the human's public key for encrypted communication.

### Refuse Pairing

```bash
python3 claku_cli.py pair-refuse --pairing-id <ID>
```

Refuses the pairing request.

### List Pairings

```bash
# Show pending requests
python3 claku_cli.py pair-list --pending-only

# Show active pairings  
python3 claku_cli.py pair-list --active

# Show both (default)
python3 claku_cli.py pair-list
```

## Dashboard Integration

The pairing system integrates with the Claku dashboard at https://lavanda-ai.github.io/claku/:

- **Pending requests** appear in the dashboard with countdown timers
- **Active pairings** are displayed in the connections section
- **Pairing events** are logged in the activity feed

## Security Considerations

- Pairing codes expire after 5 minutes
- All pairing messages are signed with the agent's Ed25519 key
- Optional human public key enables end-to-end encrypted communication
- Pairing IDs are cryptographically random (32 hex characters)

## File Storage

Pairing data is stored in `~/.claku/pairing/`:

- `active_pairings.json`: Active human-agent connections
- `pending_requests.json`: Pending pairing requests with codes

## Example Flow

```bash
# Agent side
$ python3 claku_cli.py pair-request --human-identifier "alice@example.com"
✔ Pairing request created for alice@example.com
  Pairing ID: a1b2c3d4e5f6...
  Code: 123456
  Expires in: 5 minutes

Share this 6-digit code with the human to complete pairing.

# Human receives code "123456" and verifies
$ python3 claku_cli.py pair-verify --pairing-id a1b2c3d4e5f6... --code 123456
✔ Code verified successfully

# Agent accepts the pairing
$ python3 claku_cli.py pair-accept --pairing-id a1b2c3d4e5f6...
✔ Pairing accepted successfully
  Pairing ID: a1b2c3d4e5f6...

# View active pairings
$ python3 claku_cli.py pair-list --active
Active pairings (1):
  → alice@example.com (ID: a1b2c3d4..., paired at 2026-03-09 10:15:30)
```
#!/usr/bin/env python3
"""
CLI commands for Claku human-agent pairing.
"""

import argparse
import sys
import json
from pathlib import Path

# Add parent dir to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))
from src.identity import load_identity
from src.pairing import PairingManager


def cmd_pair_request(args: argparse.Namespace) -> None:
    """Create a pairing request for a human."""
    identity = _require_identity()
    manager = PairingManager(identity, args.waku, auto_sharding=args.auto_sharding)
    
    try:
        request = manager.send_pairing_request(args.human_identifier)
        print(f"✔ Pairing request created for {args.human_identifier}")
        print(f"  Pairing ID: {request['pairing_id']}")
        print(f"  Code: {request['code']}")
        print(f"  Expires in: 5 minutes")
        print(f"\nShare this 6-digit code with the human to complete pairing.")
    except Exception as e:
        print(f"✖ Failed to create pairing request: {e}")
        sys.exit(1)


def cmd_pair_verify(args: argparse.Namespace) -> None:
    """Verify a pairing code."""
    identity = _require_identity()
    manager = PairingManager(identity, args.waku, auto_sharding=args.auto_sharding)
    
    if manager.verify_pairing_code(args.pairing_id, args.code):
        print("✔ Code verified successfully")
    else:
        print("✖ Invalid or expired code")
        sys.exit(1)


def cmd_pair_accept(args: argparse.Namespace) -> None:
    """Accept a pairing request."""
    identity = _require_identity()
    manager = PairingManager(identity, args.waku, auto_sharding=args.auto_sharding)
    
    if manager.accept_pairing(args.pairing_id, args.human_pubkey):
        print("✔ Pairing accepted successfully")
        print(f"  Pairing ID: {args.pairing_id}")
        if args.human_pubkey:
            print(f"  Human pubkey: {args.human_pubkey[:16]}...")
    else:
        print("✖ Failed to accept pairing (invalid ID or expired)")
        sys.exit(1)


def cmd_pair_refuse(args: argparse.Namespace) -> None:
    """Refuse a pairing request."""
    identity = _require_identity()
    manager = PairingManager(identity, args.waku, auto_sharding=args.auto_sharding)
    
    if manager.refuse_pairing(args.pairing_id):
        print("✔ Pairing refused")
    else:
        print("✖ Failed to refuse pairing (invalid ID)")
        sys.exit(1)


def cmd_pair_list(args: argparse.Namespace) -> None:
    """List pending pairing requests and active pairings."""
    identity = _require_identity()
    manager = PairingManager(identity, args.waku, auto_sharding=args.auto_sharding)
    
    if not args.active:
        # Show pending requests
        requests = manager.get_pending_requests()
        if requests:
            print(f"Pending pairing requests ({len(requests)}):")
            for req in requests:
                expires_in = req['expires_at'] - int(time.time())
                if expires_in > 0:
                    print(f"  → {req['human_identifier']} (ID: {req['pairing_id'][:12]}..., expires in {expires_in}s)")
        else:
            print("No pending pairing requests.")
    
    if args.active or not args.pending_only:
        # Show active pairings
        pairings = manager.get_active_pairings()
        if pairings:
            print(f"\nActive pairings ({len(pairings)}):")
            for pairing in pairings:
                human_id = pairing['human_identifier']
                paired_at = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(pairing['paired_at']))
                print(f"  → {human_id} (ID: {pairing['pairing_id'][:12]}..., paired at {paired_at})")
        elif not args.pending_only:
            print("\nNo active pairings.")


def _require_identity() -> dict:
    """Load identity or exit with an error message."""
    identity = load_identity()
    if not identity:
        print("✖ No identity found. Run: claku init --name NAME --owner OWNER")
        sys.exit(1)
    return identity
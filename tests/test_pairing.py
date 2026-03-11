#!/usr/bin/env python3
"""
Test suite for Claku pairing system.
"""

import os
import sys
import tempfile
import shutil
from pathlib import Path

# Add src to path
src_path = str(Path(__file__).parent.parent / "src")
if src_path not in sys.path:
    sys.path.insert(0, src_path)

from pairing import PairingManager
from identity import get_or_create_identity


def test_pairing_workflow():
    """Test the complete pairing workflow."""
    # Create temporary directory for test
    with tempfile.TemporaryDirectory() as temp_dir:
        os.environ["CLAKU_DIR"] = temp_dir
        
        # Create identity
        identity = get_or_create_identity("test-agent", "test-owner", ["test"], force=True)
        
        # Create pairing manager
        manager = PairingManager(identity, "http://localhost:8645")
        
        # Test 1: Create pairing request
        human_id = "test@example.com"
        request = manager.create_pairing_request(human_id)
        
        assert "pairing_id" in request
        assert "code" in request
        assert len(request["code"]) == 6
        assert request["human_identifier"] == human_id
        assert request["agent_pubkey"] == identity["pubkey"]
        assert request["status"] == "pending"
        
        pairing_id = request["pairing_id"]
        code = request["code"]
        
        # Test 2: Verify correct code
        assert manager.verify_pairing_code(pairing_id, code) == True
        
        # Test 3: Verify incorrect code
        assert manager.verify_pairing_code(pairing_id, "000000") == False
        
        # Test 4: Accept pairing
        assert manager.accept_pairing(pairing_id) == True
        
        # Test 5: Verify pairing is now active
        pairings = manager.get_active_pairings()
        assert len(pairings) == 1
        assert pairings[0]["human_identifier"] == human_id
        assert pairings[0]["pairing_id"] == pairing_id
        assert pairings[0]["status"] == "active"
        
        # Test 6: Try to verify expired pairing (should fail)
        assert manager.verify_pairing_code(pairing_id, code) == False
        
        print("✓ All pairing tests passed!")


def test_pairing_expiration():
    """Test pairing request expiration."""
    with tempfile.TemporaryDirectory() as temp_dir:
        os.environ["CLAKU_DIR"] = temp_dir
        
        identity = get_or_create_identity("test-agent2", "test-owner2", ["test"], force=True)
        manager = PairingManager(identity, "http://localhost:8645")
        
        # Create request
        request = manager.create_pairing_request("expire@test.com")
        pairing_id = request["pairing_id"]
        code = request["code"]
        
        # Should be valid initially
        assert manager.verify_pairing_code(pairing_id, code) == True
        
        # Modify expiration to be in the past
        requests = manager._load_requests()
        requests[pairing_id]["expires_at"] = 0
        manager._save_requests(requests)
        
        # Should now be invalid
        assert manager.verify_pairing_code(pairing_id, code) == False
        
        print("✓ Pairing expiration test passed!")


def test_pairing_refuse():
    """Test refusing a pairing request."""
    with tempfile.TemporaryDirectory() as temp_dir:
        os.environ["CLAKU_DIR"] = temp_dir
        
        identity = get_or_create_identity("test-agent3", "test-owner3", ["test"], force=True)
        manager = PairingManager(identity, "http://localhost:8645")
        
        # Create request
        request = manager.create_pairing_request("refuse@test.com")
        pairing_id = request["pairing_id"]
        
        # Refuse the pairing
        assert manager.refuse_pairing(pairing_id) == True
        
        # Should not be in pending requests anymore
        requests = manager.get_pending_requests()
        assert len(requests) == 0
        
        # Should not be able to accept refused pairing
        assert manager.accept_pairing(pairing_id) == False
        
        print("✓ Pairing refuse test passed!")


if __name__ == "__main__":
    test_pairing_workflow()
    test_pairing_expiration()
    test_pairing_refuse()
    print("🎉 All pairing tests completed successfully!")
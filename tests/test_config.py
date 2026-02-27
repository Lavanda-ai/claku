#!/usr/bin/env python3
"""Tests for Claku config module."""

import sys, os, json, tempfile, unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.config import load_config, save_config, get, set_value, DEFAULTS, _parse_env_value


class TestDefaults(unittest.TestCase):
    def test_defaults_present(self):
        self.assertIn("waku_url", DEFAULTS)
        self.assertIn("auto_sharding", DEFAULTS)
        self.assertIn("cluster_id", DEFAULTS)
        self.assertTrue(DEFAULTS["auto_sharding"])

    def test_load_returns_defaults_when_no_file(self):
        with patch("src.config.CONFIG_PATH", "/tmp/nonexistent_claku_config.json"):
            config = load_config()
            self.assertEqual(config["waku_url"], "http://node.claku.xyz:8645")
            self.assertTrue(config["auto_sharding"])


class TestFileConfig(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.config_path = os.path.join(self.tmpdir, "config.json")

    def tearDown(self):
        if os.path.exists(self.config_path):
            os.remove(self.config_path)
        os.rmdir(self.tmpdir)

    def test_save_and_load(self):
        with patch("src.config.CONFIG_PATH", self.config_path), \
             patch("src.config.CONFIG_DIR", self.tmpdir):
            save_config({"waku_url": "http://custom:9999", "auto_sharding": True})
            config = load_config()
            self.assertEqual(config["waku_url"], "http://custom:9999")
            self.assertTrue(config["auto_sharding"])

    def test_file_overrides_defaults(self):
        with open(self.config_path, "w") as f:
            json.dump({"cluster_id": 1}, f)
        with patch("src.config.CONFIG_PATH", self.config_path):
            config = load_config()
            self.assertEqual(config["cluster_id"], 1)
            # Other defaults still present
            self.assertIn("waku_url", config)

    def test_corrupt_file_falls_back_to_defaults(self):
        with open(self.config_path, "w") as f:
            f.write("not json{{{")
        with patch("src.config.CONFIG_PATH", self.config_path):
            config = load_config()
            self.assertEqual(config["waku_url"], DEFAULTS["waku_url"])


class TestEnvOverrides(unittest.TestCase):
    def test_env_overrides_file(self):
        with patch.dict(os.environ, {"CLAKU_WAKU_URL": "http://env:1234"}), \
             patch("src.config.CONFIG_PATH", "/tmp/nonexistent.json"):
            config = load_config()
            self.assertEqual(config["waku_url"], "http://env:1234")

    def test_bool_env_parsing(self):
        for truthy in ("1", "true", "True", "yes", "on"):
            with patch.dict(os.environ, {"CLAKU_AUTO_SHARDING": truthy}), \
                 patch("src.config.CONFIG_PATH", "/tmp/nonexistent.json"):
                config = load_config()
                self.assertTrue(config["auto_sharding"], f"Failed for {truthy}")

        for falsy in ("0", "false", "no", "off"):
            with patch.dict(os.environ, {"CLAKU_AUTO_SHARDING": falsy}), \
                 patch("src.config.CONFIG_PATH", "/tmp/nonexistent.json"):
                config = load_config()
                self.assertFalse(config["auto_sharding"], f"Failed for {falsy}")

    def test_int_env_parsing(self):
        with patch.dict(os.environ, {"CLAKU_CLUSTER_ID": "1"}), \
             patch("src.config.CONFIG_PATH", "/tmp/nonexistent.json"):
            config = load_config()
            self.assertEqual(config["cluster_id"], 1)


class TestParseEnvValue(unittest.TestCase):
    def test_bool_keys(self):
        self.assertTrue(_parse_env_value("auto_sharding", "true"))
        self.assertFalse(_parse_env_value("auto_sharding", "false"))

    def test_int_keys(self):
        self.assertEqual(_parse_env_value("cluster_id", "42"), 42)

    def test_string_keys(self):
        self.assertEqual(_parse_env_value("waku_url", "http://x"), "http://x")


class TestGetSet(unittest.TestCase):
    def test_get_default(self):
        with patch("src.config.CONFIG_PATH", "/tmp/nonexistent.json"):
            self.assertEqual(get("waku_url"), "http://node.claku.xyz:8645")
            self.assertIsNone(get("nonexistent"))
            self.assertEqual(get("nonexistent", "fallback"), "fallback")


if __name__ == "__main__":
    unittest.main()

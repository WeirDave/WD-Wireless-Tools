from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import tools.cloud_manager as cloud_manager


SAMPLE_COOKIES = [
    {"name": "AccessToken", "value": "secret-access-token",
     "domain": ".ekahau.cloud", "path": "/"},
    {"name": "CSRF-Token", "value": "secret-csrf-token",
     "domain": ".ekahau.cloud", "path": "/"},
]
SAMPLE_CSRF = "secret-csrf-token"


class FakeKeyring:
    def __init__(self, fail_write=False):
        self.secret = None
        self.fail_write = fail_write

    def get_password(self, service, username):
        return self.secret

    def set_password(self, service, username, value):
        if self.fail_write:
            raise RuntimeError("vault unavailable")
        self.secret = value

    def delete_password(self, service, username):
        self.secret = None


class CloudCredentialTests(unittest.TestCase):
    def setUp(self):
        if cloud_manager.Fernet is None:
            self.skipTest("cryptography is not installed")
        self.temp_dir = tempfile.TemporaryDirectory()
        root = Path(self.temp_dir.name)
        self.legacy_file = root / "cookies.json"
        self.encrypted_file = root / "cookies.enc"
        self.keyring = FakeKeyring()
        self.patches = [
            patch.object(cloud_manager, "CONFIG_DIR", root),
            patch.object(cloud_manager, "COOKIE_FILE", self.legacy_file),
            patch.object(cloud_manager, "ENCRYPTED_COOKIE_FILE", self.encrypted_file),
            patch.object(cloud_manager, "keyring", self.keyring),
        ]
        for active_patch in self.patches:
            active_patch.start()

    def tearDown(self):
        for active_patch in reversed(self.patches):
            active_patch.stop()
        self.temp_dir.cleanup()

    def _write_legacy(self):
        self.legacy_file.write_text(json.dumps({
            "cookies": SAMPLE_COOKIES,
            "csrfToken": SAMPLE_CSRF,
        }), encoding="utf-8")

    def test_new_session_is_encrypted_and_round_trips(self):
        saved = cloud_manager.save_cookies_to_disk(SAMPLE_COOKIES, SAMPLE_CSRF)

        self.assertTrue(saved)
        self.assertFalse(self.legacy_file.exists())
        self.assertTrue(self.encrypted_file.exists())
        self.assertNotIn(b"secret-access-token", self.encrypted_file.read_bytes())
        self.assertIsNotNone(self.keyring.secret)
        self.assertEqual(cloud_manager.load_cookies_from_disk(),
                         (SAMPLE_COOKIES, SAMPLE_CSRF))

    def test_legacy_file_migrates_only_after_verified_secure_write(self):
        self._write_legacy()

        self.assertEqual(cloud_manager.load_cookies_from_disk(),
                         (SAMPLE_COOKIES, SAMPLE_CSRF))
        self.assertFalse(self.legacy_file.exists())
        self.assertTrue(self.encrypted_file.exists())
        self.assertEqual(cloud_manager.load_cookies_from_disk(),
                         (SAMPLE_COOKIES, SAMPLE_CSRF))

    def test_failed_migration_keeps_legacy_session_for_a_later_retry(self):
        self._write_legacy()
        self.keyring.fail_write = True

        self.assertEqual(cloud_manager.load_cookies_from_disk(),
                         (SAMPLE_COOKIES, SAMPLE_CSRF))
        self.assertTrue(self.legacy_file.exists())
        self.assertFalse(self.encrypted_file.exists())

    def test_interrupted_migration_removes_matching_plaintext_on_next_load(self):
        self.assertTrue(cloud_manager.save_cookies_to_disk(SAMPLE_COOKIES, SAMPLE_CSRF))
        self._write_legacy()

        self.assertEqual(cloud_manager.load_cookies_from_disk(),
                         (SAMPLE_COOKIES, SAMPLE_CSRF))
        self.assertFalse(self.legacy_file.exists())

    def test_new_session_never_falls_back_to_plaintext(self):
        self.keyring.fail_write = True

        self.assertFalse(cloud_manager.save_cookies_to_disk(SAMPLE_COOKIES, SAMPLE_CSRF))
        self.assertFalse(self.legacy_file.exists())
        self.assertFalse(self.encrypted_file.exists())

    def test_tampered_ciphertext_is_rejected(self):
        self.assertTrue(cloud_manager.save_cookies_to_disk(SAMPLE_COOKIES, SAMPLE_CSRF))
        self.encrypted_file.write_bytes(self.encrypted_file.read_bytes() + b"tampered")

        self.assertEqual(cloud_manager.load_cookies_from_disk(), (None, None))

    def test_forget_removes_files_and_vault_key(self):
        self._write_legacy()
        self.assertTrue(cloud_manager.save_cookies_to_disk(SAMPLE_COOKIES, SAMPLE_CSRF))

        self.assertTrue(cloud_manager.clear_saved_cookies())
        self.assertFalse(self.legacy_file.exists())
        self.assertFalse(self.encrypted_file.exists())
        self.assertIsNone(self.keyring.secret)


if __name__ == "__main__":
    unittest.main()

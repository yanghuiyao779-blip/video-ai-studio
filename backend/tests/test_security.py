import os

os.environ.setdefault("APP_SECRET_KEY", "a" * 48)
os.environ.setdefault("APP_ENCRYPTION_KEY", "b" * 48)
os.environ.setdefault("ADMIN_PASSWORD", "a-strong-test-password")

from app.core.security import decrypt_secret, encrypt_secret, hash_password, verify_password


def test_password_hashing():
    password_hash = hash_password("correct horse battery staple")
    assert verify_password("correct horse battery staple", password_hash)
    assert not verify_password("wrong", password_hash)


def test_secret_roundtrip():
    encrypted = encrypt_secret("test-secret-value")
    assert encrypted != "test-secret-value"
    assert decrypt_secret(encrypted) == "test-secret-value"

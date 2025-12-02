from __future__ import annotations

import base64
import logging
import os
import tempfile
from pathlib import Path

logger = logging.getLogger("TwitchDrops.cookies")

try:
    import keyring
    from keyring.errors import KeyringError
except Exception:
    keyring = None
    KeyringError = Exception

try:
    from pyrage import passphrase
except Exception:
    passphrase = None

_AGE_SERVICE_NAME = "twitch-drop-miner"
_AGE_KEY_NAME = "age-cookie-key"
_AGE_KEY_BYTES = 32
_AGE_HEADER_PREFIX = b"age-encryption.org/"
_AGE_ARMOR_PREFIX = b"-----BEGIN AGE ENCRYPTED FILE-----"


def load_cookie_jar(path: Path, cookie_jar) -> bool:
    """
    Load cookies from disk into the provided jar.
    Returns True if the on-disk file was legacy/unencrypted and should be re-saved.
    """
    if not path.exists():
        _ensure_age_key()
        return False

    raw = _read_bytes(path)
    if raw is None:
        return False

    if _looks_age_encrypted(raw):
        key = _ensure_age_key()
        if key is None:
            logger.error("Encrypted cookies present but no keyring-backed age key is available")
            return False
        data = _decrypt_age(raw, key)
        if data is None:
            return False
        _load_from_bytes(cookie_jar, data, path)
        return False

    try:
        cookie_jar.load(path)
    except Exception:
        logger.exception("Failed to load cookies file; ignoring")
        return False
    _ensure_age_key()
    return True


def save_cookie_jar(path: Path, cookie_jar) -> None:
    try:
        plaintext = _serialize_cookie_jar(cookie_jar, path)
    except Exception:
        logger.exception("Failed to serialize cookies; not saving")
        return

    key = _ensure_age_key()
    if key is None:
        logger.error("Cannot save cookies securely because no keyring-backed age key is available")
        return

    encrypted = _encrypt_age(plaintext, key)
    if encrypted is None:
        return
    _write_bytes(path, encrypted)


def _encrypt_age(data: bytes, key: str) -> bytes | None:
    if passphrase is None:
        logger.error("pyrage is not installed; cannot encrypt cookies with age")
        return None
    try:
        return passphrase.encrypt(data, key)
    except Exception:
        logger.exception("Failed to encrypt cookies with age")
        return None


def _decrypt_age(data: bytes, key: str) -> bytes | None:
    if passphrase is None:
        logger.error("pyrage is not installed; cannot decrypt cookies with age")
        return None
    try:
        return passphrase.decrypt(data, key)
    except Exception:
        logger.exception("Failed to decrypt cookies file; ignoring")
        return None


def _looks_age_encrypted(raw: bytes) -> bool:
    return raw.startswith(_AGE_HEADER_PREFIX) or raw.startswith(_AGE_ARMOR_PREFIX)


def _ensure_age_key() -> str | None:
    key = _read_age_key()
    if key:
        return key
    return _create_age_key()


def _read_age_key() -> str | None:
    if keyring is None:
        return None
    try:
        value = keyring.get_password(_AGE_SERVICE_NAME, _AGE_KEY_NAME)
    except KeyringError:
        logger.exception("Failed to read cookies encryption key from the OS keyring")
        return None
    if not value:
        return None

    normalized = _normalize_key_value(value)
    if normalized is None:
        logger.warning("Ignoring invalid cookies encryption key stored in the OS keyring")
        return None
    if normalized != value:
        _store_age_key(normalized)
    return normalized


def _create_age_key() -> str | None:
    if keyring is None:
        logger.error("python-keyring is not available; install it to secure cookies.")
        return None
    if not _keyring_is_secure():
        return None
    key_bytes = os.urandom(_AGE_KEY_BYTES)
    encoded = base64.urlsafe_b64encode(key_bytes).decode("ascii")
    if _store_age_key(encoded):
        logger.info("Generated new cookies encryption key and stored it in the OS keyring")
        return encoded
    return None


def _store_age_key(value: str) -> bool:
    if keyring is None:
        return False
    try:
        keyring.set_password(_AGE_SERVICE_NAME, _AGE_KEY_NAME, value)
        return True
    except KeyringError:
        logger.exception("Failed to store cookies encryption key in the OS keyring")
        return False


def _keyring_is_secure() -> bool:
    backend = keyring.get_keyring()
    module = backend.__module__
    name = backend.__class__.__name__
    if module.startswith("keyring.backends.fail") or module.startswith("keyring.backends.null"):
        logger.error("No usable system keyring backend available; cannot secure cookies (backend=%s.%s)", module, name)
        return False
    if module.startswith("keyrings.alt.") or "Plaintext" in name or "Uncrypted" in name:
        logger.error("Refusing to store cookies key in insecure keyring backend (%s.%s)", module, name)
        return False
    return True


def _normalize_key_value(value: str) -> str | None:
    value = value.strip()
    raw = _decode_key_material(value)
    if raw is None:
        return None
    if len(raw) < _AGE_KEY_BYTES:
        return None
    raw = raw[:_AGE_KEY_BYTES]
    return base64.urlsafe_b64encode(raw).decode("ascii")


def _decode_key_material(value: str) -> bytes | None:
    for decoder in (_b64decode_value, bytes.fromhex):
        try:
            data = decoder(value)
        except Exception:
            continue
        if data:
            return data
    return None


def _b64decode_value(value: str) -> bytes:
    padded = value + "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(padded.encode("ascii"))


def _read_bytes(path: Path) -> bytes | None:
    try:
        return path.read_bytes()
    except Exception:
        logger.exception("Failed to read cookies file")
        return None


def _serialize_cookie_jar(cookie_jar, target: Path) -> bytes:
    fd, name = tempfile.mkstemp(prefix="cookies.", suffix=".tmp", dir=target.parent)
    os.close(fd)
    tmp_path = Path(name)
    try:
        cookie_jar.save(tmp_path)
        return tmp_path.read_bytes()
    finally:
        tmp_path.unlink(missing_ok=True)


def _load_from_bytes(cookie_jar, data: bytes, target: Path) -> None:
    fd, name = tempfile.mkstemp(prefix="cookies.", suffix=".tmp", dir=target.parent)
    os.close(fd)
    tmp_path = Path(name)
    try:
        tmp_path.write_bytes(data)
        cookie_jar.load(tmp_path)
    except Exception:
        logger.exception("Failed to load cookies file; ignoring")
    finally:
        tmp_path.unlink(missing_ok=True)


def _write_bytes(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        path.write_bytes(data)
    except Exception:
        logger.exception("Failed to write cookies file")

# Credential-crypto review

**Date:** 2026-04-21
**Files:**

- `packages/central/src/monctl_central/credentials/crypto.py` — central at-rest encryption (PostgreSQL `credentials.encrypted_value`)
- `packages/collector/src/monctl_collector/central/credentials.py` — collector local cache (SQLite)

## Overall assessment

**No critical issues.** Both sides use peer-reviewed AEAD primitives from `cryptography` with secure nonce/IV handling. Three low-priority gaps documented below; none warrant a hotfix. Ship-as-is is defensible.

## Central: `crypto.py`

| Property       | Value                                     | Assessment                                                                                         |
| -------------- | ----------------------------------------- | -------------------------------------------------------------------------------------------------- |
| Cipher         | AES-256-GCM (AEAD) via `AESGCM`           | ✅ Modern, authenticated                                                                           |
| Key size       | 256 bits                                  | ✅                                                                                                 |
| Nonce          | `os.urandom(12)`, 96-bit, per-message     | ✅ NIST SP 800-38D §8.2.2 random-nonce bound is ~2³² messages/key; credential store won't approach |
| Tag            | Implicit GCM tag appended by library      | ✅                                                                                                 |
| AAD            | `None` (no additional authenticated data) | ⚠ Ciphertext not bound to row ID — theoretical row-swap attack requires DB write access            |
| Key source     | `MONCTL_ENCRYPTION_KEY` env, 64 hex chars | ✅ Validated on read                                                                               |
| Serialization  | `base64url(nonce ‖ ciphertext+tag)`       | ⚠ No version prefix → cannot distinguish ciphertexts across future cipher/key changes              |
| Error handling | `InvalidTag` propagates                   | ✅                                                                                                 |

### Observations

- `_get_key()` is called on every encrypt/decrypt — minor perf miss (re-imports `settings`, re-validates hex). Not a security issue; could cache the key bytes module-local after first successful read.
- No visible key-rotation path. Rotating requires:
  1. A ciphertext version / key-ID prefix (not present).
  2. A migration that decrypts-with-old + encrypts-with-new for every row.
     Neither exists today. Acceptable for a single-operator deployment; painful the day you need it.

## Collector: `credentials.py`

| Property         | Value                                                                         | Assessment                                                                     |
| ---------------- | ----------------------------------------------------------------------------- | ------------------------------------------------------------------------------ |
| Cipher           | Fernet (AES-128-CBC + HMAC-SHA256)                                            | ✅ Safe, battle-tested                                                         |
| Key size         | 128 bits                                                                      | ✅ Sufficient; lower than central but different cipher, different blast radius |
| IV               | Random per encrypt, managed by Fernet                                         | ✅                                                                             |
| Tag              | HMAC-SHA256 appended by Fernet                                                | ✅                                                                             |
| Key source       | `ENCRYPTION_KEY` env (64 hex → base64url) OR `Fernet.generate_key()` if unset | ⚠ See below                                                                    |
| Error handling   | `InvalidToken` on tamper/key-mismatch → refresh from central                  | ✅ Graceful                                                                    |
| Offline fallback | Serves stale cache indefinitely when central down                             | ✅ Intentional (monitoring must not stop)                                      |

### Observations

- **Auto-generated key footgun** (`make_key(None)` → `Fernet.generate_key()`): if `ENCRYPTION_KEY` is unset, a fresh random key is generated on every restart and the local SQLite cache becomes unreadable. The code handles this gracefully (catches `InvalidToken`, refetches from central), but it's **silent** — no log line warns that the key wasn't persisted. In prod this means unnecessary central-API load after every restart; in air-gapped demo setups it means monitoring breaks for one refresh cycle after every collector restart. One-liner to fix: emit `logger.warning("encryption_key_unset_generating_ephemeral")` in the `None`-branch of `make_key`.
- Central/collector key **mismatch is intentional** — each side encrypts its own at-rest store; ciphertext never crosses the wire. Wire transfer happens over TLS-plaintext inside the API response body (see F-X-010 TLS audit).
- Stale-cache behaviour keeps polling alive indefinitely with a rotated-in-central credential. Correct for availability; means a compromised credential requires an explicit collector restart + new fetch to invalidate. Document as known trade-off.
- `logger.warning("credential_refresh_failed", error=str(exc))` includes `str(exc)`. If the central API ever embeds fragments of the fetched value in an error message, they'd land in collector logs. No evidence it does today, but worth scrubbing if central's error-formatting ever changes.

## Recommendations (all low priority)

1. **[collector]** Add `logger.warning("encryption_key_unset — ephemeral key will lose cache on restart")` to `CredentialManager.make_key(None)` branch. One line. Ship in a follow-up PR.
2. **[central]** Add a 1-byte version prefix to `encrypt_secret` output: `bytes([0x01]) + nonce + ciphertext`. Decrypt branches on prefix. Future-proofs key/cipher rotation. ~20-line change plus a migration that rewrites existing ciphertexts.
3. **[central]** When encrypting per-row credentials, pass `AAD = str(credential_id).encode()` so a DB row-swap is detected as an auth failure. Requires passing `credential_id` through call sites; small but touches every encrypt/decrypt path.

None of these are security-critical. #1 is the only one worth doing soon.

## Not flagged (deliberate design)

- Different ciphers on each side — each side owns its own at-rest store; ciphertexts never cross the wire.
- No key-caching in `_get_key` — current call rate is low (credential writes/reads happen on user action or periodic refresh, not in hot path).
- Stale-cache indefinite serving — monitoring availability > credential freshness under central outage.

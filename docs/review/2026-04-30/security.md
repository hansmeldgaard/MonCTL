# Security Findings — Review #2 (2026-04-30)

## Summary

- **47 findings**: 7 HIGH / 20 MED / 16 LOW / 4 INFO
- **Carry-over status**: F-CEN-001 (cookie secure), F-CEN-014 (collector ownership), F-CEN-037 (logs admin gate), F-COL-031 (pip whitelist), F-CEN-012 (constant-time compare on collector API) confirmed fixed. F-CEN-004 (login rate-limit) and F-CEN-018 (WS query-param token fallback) remain open.

The new attack surfaces this cycle are **(a) the customer installer (`monctl_ctl`)**, which mints cluster secrets and SSH-deploys compose bundles, and **(b) the OAuth2 provider + Superset SSO + tenant RLS triad** that ships row-level isolation across two products. The installer is the higher-risk surface: a tarfile path-traversal in `bundle load`, hardcoded prod IPs as Superset config defaults, `MONCTL_VERIFY_SSL: "false"` baked into customer-shipped collector compose, weak Redis/sentinel posture (no auth, bound to host), and a 67-bit pronounceable admin password that pairs with a still-rate-limit-less `/v1/auth/login`. The OAuth2 provider itself is well-defended (exact-match redirect_uri, single-use Redis-stored codes via GETDEL, HMAC-compared client_secret). The alerting DSL and CH tenant scope (Layer 3) also looked solid — `_assert_safe_identifier` plus parameter binding everywhere I sampled. Most HIGH-severity findings cluster on the installer; central HIGHs are documented carry-overs that haven't sunset their legacy paths.

---

## Installer

### S-INST-001 — `tarfile.extractall` with no filter on customer-supplied bundles
- **Severity**: HIGH
- **File**: `packages/installer/src/monctl_installer/commands/bundle.py:131-148`
- **Description**: `monctl_ctl bundle load <path>` calls `tf.extractall(work)` on a tarball the operator hands in. Pre-Python-3.12 hosts have no default member filter, so a bundle crafted with `../../../etc/cron.d/...` entries can write outside `work`. Bundles are typically created internally, but the command takes any path — a phished bundle, a typo'd download, or a substituted artifact at the registry edge becomes RCE on the operator workstation.
- **Fix sketch**: Pass `filter='data'` (PEP 706) to `extractall` and warn loudly on Python < 3.12. Optionally validate every member's `name` doesn't contain `..` or absolute paths before extracting.

### S-INST-002 — Hardcoded prod IPs as Superset config defaults ship to customers
- **Severity**: HIGH
- **Files**:
  - `packages/installer/src/monctl_installer/render/templates/config/superset_config.py.j2:177` (`http://10.145.210.41:8443`)
  - `packages/installer/src/monctl_installer/render/templates/config/superset_config.py.j2:288, 298, 304, 757` (`https://10.145.210.40`)
  - `packages/central/src/monctl_central/config.py:112` (`oauth_issuer = "https://10.145.210.40"`)
- **Description**: The customer-shipped Superset config falls back to MonCTL's internal dev IP and VIP if the matching env vars aren't set. In a customer environment this either fails closed (no SSO) or — if the customer happens to run an exposed proxy on 10.145.210.41 — issues OAuth tokens against the wrong issuer.
- **Fix sketch**: Replace `os.environ.get("...", "<default>")` with `os.environ["..."]` so a missing var fails loudly at boot. Defaults should never silently point at MonCTL infrastructure.

### S-INST-003 — Customer collector deploys with `MONCTL_VERIFY_SSL: "false"` hardcoded
- **Severity**: HIGH
- **File**: `packages/installer/src/monctl_installer/render/templates/compose/collector.yml.j2:14, 46, 68`
- **Description**: Every collector container ships with `MONCTL_VERIFY_SSL: "false"` baked into the compose template. The installer never offers a knob to flip this on. For any customer who runs MonCTL with a real CA-issued cert, the installer-shipped collectors are MITM-targets-by-default forever.
- **Fix sketch**: Make the value a Jinja variable `{{ verify_ssl | default('false') }}`, wire it to an inventory field `cluster.tls_verify`, default `true` once the inventory has a non-self-signed cert hint.

### S-INST-004 — SSH `set_missing_host_key_policy(AutoAddPolicy)` — TOFU silently accepts any host key
- **Severity**: HIGH
- **File**: `packages/installer/src/monctl_installer/remote/ssh.py:101-113`
- **Description**: Every paramiko connection auto-accepts unknown host keys. An attacker on the network between the operator workstation and a target host can present any key on first connection. Combined with `allow_agent=True` (line 108), the deployer's SSH agent gets MITM'd along with the secrets.env scp.
- **Fix sketch**: Default to `paramiko.RejectPolicy()`, load `~/.ssh/known_hosts` via `client.load_system_host_keys()`. Add a `--accept-new-hostkeys` flag for first-time onboarding that switches to `AutoAddPolicy` and writes to disk.

### S-INST-005 — Pronounceable admin password is ~67 bits in a no-rate-limit context
- **Severity**: MED
- **Files**: `packages/installer/src/monctl_installer/secrets/generator.py:83-99`; `packages/central/src/monctl_central/auth/router.py` (no rate-limit, F-CEN-004 still open)
- **Description**: `_pronounceable_password(length=20)` produces ~9 alternating CV syllables (≈61 bits) plus a 2-digit suffix (≈6.5 bits) ≈ **67 bits of entropy**. Pronounceable for memorability is fine in isolation, but `/v1/auth/login` has no rate-limit. 67 bits is brute-forceable in days against an unrate-limited endpoint with HAProxy fanning out to 4 centrals.
- **Fix sketch**: Either bump the syllable count to 12+ (≈84 bits) or close F-CEN-004 first.

### S-INST-006 — `superset-init.sh` runs `pip install` from PyPI on every container start
- **Severity**: MED
- **File**: `packages/installer/src/monctl_installer/render/templates/config/superset-requirements.txt.j2`, executed by `superset-init.sh.j2:14-15`
- **Description**: Every Superset boot runs `pip install --quiet --no-cache-dir -r /app/docker/requirements-local.txt`. Three packages, two version-pinned, one with `>=`, none hash-pinned. A compromised PyPI index, a typo-squat collision, or a clickhouse-connect supply-chain compromise becomes RCE inside Superset (which holds the OAuth client_secret + ClickHouse readonly=2 creds). Air-gapped customers can't even use this code path.
- **Fix sketch**: Bake the three packages into a customer-shipped Superset image during `monctl_ctl bundle create`; remove the runtime pip step. Interim: add `--require-hashes` and pin every transitive.

### S-INST-007 — Redis Sentinel + Redis containers ship without auth, bound to host network
- **Severity**: MED
- **Files**: `packages/installer/src/monctl_installer/render/templates/compose/redis.yml.j2:7, 20, 36`; `config/sentinel.conf.j2:4-10`
- **Description**: Redis and Sentinel both run with `network_mode: host`, binding to `0.0.0.0:6379` and `0.0.0.0:26379`. No `requirepass`, no `sentinel auth-pass`. Anyone who can reach those ports can issue arbitrary Redis commands (FLUSHALL, CONFIG SET dir/dbfilename for write-anywhere RCE on older redis, MONITOR to dump session keys / OAuth codes / API-key cache).
- **Fix sketch**: Generate a `redis_password` in `SecretBundle`, render `requirepass` + `masterauth` + `sentinel auth-pass`, and require central + collector + Superset to thread the password through their `MONCTL_REDIS_URL` / cache configs.

### S-INST-008 — `docker-stats` sidecar runs `privileged: true` with `/:/host_root:rw` shipped to every customer host
- **Severity**: MED
- **File**: `packages/installer/src/monctl_installer/render/templates/compose/docker-stats.yml.j2:6-11`
- **Description**: Customer installer always renders the docker-stats sidecar with `privileged: true`, `pid: host`, `network_mode: host`, and the host root mounted RW. The OS-upgrade flow needs this. Customers who don't want OS upgrades have no way to opt out, and the sidecar's `MONCTL_PUSH_API_KEY` (the shared collector secret) gives anyone with that key a way into the privileged container's API.
- **Fix sketch**: Make the sidecar opt-in via inventory `host.roles`. Skip rendering on hosts without an explicit `docker_stats` role.

### S-INST-009 — `superset_config.py.j2` decodes JWT without signature verification for username matching
- **Severity**: LOW
- **File**: `packages/installer/src/monctl_installer/render/templates/config/superset_config.py.j2:195-222`
- **Description**: The cross-user session-leak guard reads `request.cookies.get("access_token")`, splits on `.`, base64-decodes the payload, and compares `payload.username` to `current_user.username`. Worst case: forcing a Superset logout on an attacker-supplied cookie.
- **Fix sketch**: Verify the JWT against `MONCTL_JWT_SECRET_KEY` before reading the username claim. Or skip the optimisation and clear the session whenever an `access_token` cookie is present without a matching FAB session.

### S-INST-010 — Init wizard rollback deletes the rendered inventory but loses interactive answers
- **Severity**: LOW
- **File**: `packages/installer/src/monctl_installer/commands/init.py:159-168`
- **Description**: `_finalize` writes the inventory first, then validates, and on failure does `inventory_path.unlink(missing_ok=True)`. A non-`--from` interactive session loses every answer the operator typed in.
- **Fix sketch**: Write to a `.tmp` then rename on success; on validation failure, leave the `.tmp` for inspection.

### S-INST-011 — `secrets.env` parser doesn't reject values containing `${` placeholders
- **Severity**: LOW
- **File**: `packages/installer/src/monctl_installer/secrets/store.py:79-94`
- **Description**: Values are dropped into compose `.env` files and into `_materialise_env`'s `out.replace(f"${{{key}}}", value)`. If a secret contains `${OTHER_KEY}` text, nested expansion mid-render could leak the wrong value. Generated bundle is safe today; footgun if anyone ever lets users supply their own values via `secrets.mode=provided`.
- **Fix sketch**: Document that values must be opaque; reject any value containing `${` at validation time. Escape values during `_materialise_env` (one-pass replacement using a dict).

### S-INST-012 — `image_tag` from `monctl_ctl upgrade <version>` is unsanitised before flowing into compose YAML
- **Severity**: LOW
- **File**: `packages/installer/src/monctl_installer/commands/upgrade.py:177` (uses `compose/central.yml.j2:4` etc.)
- **Description**: `version` is a Click `argument` with no validation. A malicious operator could pass a string with embedded YAML to inject keys into the rendered compose file. Severity is LOW because the operator already has root via SSH, but a CI pipeline that takes the version string from a webhook payload elevates this.
- **Fix sketch**: Reject any `version` not matching `^[A-Za-z0-9_.-]+$` at the CLI boundary. `click.argument(..., callback=validate_version)`.

### S-INST-013 — `bundle create` writes images to `staging` directory without permission lockdown
- **Severity**: LOW
- **File**: `packages/installer/src/monctl_installer/commands/bundle.py:75-78, 110-113`
- **Description**: `staging = out_path.parent / f".{out_path.stem}.staging"` is created with default umask. An operator invoking `monctl_ctl bundle create` in a shared work dir leaks the staging dir at world-readable mode if umask is 022.
- **Fix sketch**: `os.umask(0o077)` for the duration of the build, or explicitly chmod every file/dir to 0o700 / 0o600.

### S-INST-014 — SFTP `put` chmod-after-write race on `.env` files
- **Severity**: MED
- **File**: `packages/installer/src/monctl_installer/remote/ssh.py:84-97`
- **Description**: `runner.put` opens remote file with default umask, writes content, then chmod's to the requested mode. Window where another root-readable process can capture `.env` content (mode 0o600 set after write). The deploy.py callers use this for `secrets`-bearing `.env` files (line 119–123) — exposure window is small but real on a multi-tenant host.
- **Fix sketch**: Write to `path.tmp` with explicit 0o600 mode flags then atomic rename.

### S-INST-015 — `.state.json` half-fresh half-stale on partial deploy failure
- **Severity**: LOW
- **File**: `packages/installer/src/monctl_installer/commands/deploy.py:96-103`
- **Description**: When `_apply_project` succeeds, `_save_remote_state` writes the digest. If the next project's `_apply_project` raises `SSHError`, the loop continues — the failed project's state was never written, but earlier projects' state was. On partial failure the on-disk `.state.json` is half-fresh half-stale.
- **Fix sketch**: Write `.state.json` once at the end of the per-host loop, atomically; on partial failure, write the partial state and clearly mark the failed project's digest as `"FAILED-<sha>"`.

### S-INST-016 — `_central_internal_url` description is misleading but not exploitable
- **Severity**: INFO
- **File**: `packages/installer/src/monctl_installer/render/engine.py:303-313`
- **Description**: The OAuth client_secret is sent cleartext over the internal LAN to `http://<central>:8443`. On an untrusted internal network (e.g. a customer with shared VPC), this leaks the OAuth client_secret to anyone sniffing.
- **Fix sketch**: Document the internal trust assumption explicitly. Long-term: add an HAProxy internal-only listener that exposes a TLS-terminated path to central, or install the central CA into the Superset container.

---

## Central

### S-CEN-001 — WS query-param token fallback still active; tokens leak into HAProxy access logs
- **Severity**: MED
- **File**: `packages/central/src/monctl_central/ws/router.py:43-49`
- **Description**: PR #115 was supposed to migrate WS auth to `Authorization: Bearer`, but the `?token=` query-param fallback is still wired. Tokens in URLs land in HAProxy access logs and any intermediate proxy. The collector's WS client should be on the header path everywhere by now (memory says #122 shipped).
- **Fix sketch**: Inventory current production access logs to confirm no `?token=` is in flight, then delete the fallback. Until then, scrub `?token=` from HAProxy log format.

### S-CEN-002 — Shared-secret collector path skips ownership/credential checks (legacy bypass)
- **Severity**: MED
- **Files**:
  - `packages/central/src/monctl_central/collector_api/router.py:1697-1707` (results)
  - `packages/central/src/monctl_central/collector_api/router.py:1214-1237` (credentials)
- **Description**: F-CEN-014/015 are enforced **only** when `_resolve_caller_collector` returns a Collector. The legacy shared-secret path that doesn't carry an `X-Collector-Id` header or `collector_id=` query hint and can't be matched on hostname falls through to the un-enforced path. Any holder of `MONCTL_COLLECTOR_API_KEY` who calls `/api/v1/credentials/<name>` without an identity hint gets the credential.
- **Fix sketch**: Once the customer installer ships per-collector keys (S-X-002), flip the default in `_resolve_caller_collector` to return 401 instead of falling through. Add a `MONCTL_LEGACY_SHARED_SECRET=true` env var as a 1-release transition knob.

### S-CEN-003 — `ws/auth.py` shared-secret comparison is not constant-time
- **Severity**: LOW
- **File**: `packages/central/src/monctl_central/ws/auth.py:37`
- **Description**: `if shared_secret and token == shared_secret` is plain string equality. The collector_api path was hardened with `hmac.compare_digest` (F-CEN-012 carry-over fix in `dependencies.py:491`), but the WebSocket auth path was missed.
- **Fix sketch**: `import hmac; if shared_secret and hmac.compare_digest(token, shared_secret) and collector_id_hint:`.

### S-CEN-004 — `/v1/auth/login` still has no rate limit / lockout (carry-over F-CEN-004)
- **Severity**: HIGH
- **File**: `packages/central/src/monctl_central/auth/router.py:51-117` (no `slowapi` / `Redis INCR` guard)
- **Description**: Re-verified open. Pairs with the 67-bit pronounceable admin password (S-INST-005); together they make the customer-shipped install brute-forceable.
- **Fix sketch**: Same as F-CEN-004 — Redis token-bucket keyed on `(ip, username)`; lock account for 15 min after 10 failures in 10 min. Emit a `login_locked` audit event.

### S-CEN-005 — `apply_tenant_filter` not applied on eligibility-runs and per-device probe results
- **Severity**: MED
- **Files**:
  - `packages/central/src/monctl_central/apps/router.py:2629-2722` (test_eligibility — no tenant filter on the device select)
  - `apps/router.py:2874-2891` (list_eligibility_runs — no tenant filter)
  - `apps/router.py:2894-2948` (get_eligibility_run_detail — no tenant filter)
- **Description**: A tenant-scoped user with `app:view` can `POST /v1/apps/<id>/test-eligibility` to enumerate every device the app's vendor prefix matches across the cluster, then read the resulting probe results which include device names + addresses for tenants they shouldn't see.
- **Fix sketch**: Wrap the device select with `apply_tenant_filter(stmt, auth, Device.tenant_id)` and confirm `eligibility_results` schema includes a per-row `tenant_id` so the row policy fires.

### S-CEN-006 — OAuth admin role implicitly grants Superset admin
- **Severity**: MED
- **File**: `packages/central/src/monctl_central/auth/oauth.py:139-151`
- **Description**: `_effective_superset_access` returns `"admin"` for any user with `role == "admin"` whose `superset_access` is NULL. Operator who promotes a user to MonCTL admin gives them Superset admin (full BI dataset access incl. row policies bypass) without a separate decision.
- **Fix sketch**: Make NULL → `"none"` for new rows; require admin to set `superset_access` explicitly. Or log an audit row "user X promoted to admin → effective superset_access=admin (implicit)".

### S-CEN-007 — OAuth2 provider lacks PKCE for the authorization_code grant
- **Severity**: LOW
- **File**: `packages/central/src/monctl_central/auth/oauth.py:193-275`
- **Description**: `/v1/oauth/authorize` accepts `state` and `nonce` but ignores `code_challenge` / `code_challenge_method` if presented. RFC 7636 makes PKCE optional for confidential clients, but treating it as RECOMMENDED would defang authorization-code-leak attacks.
- **Fix sketch**: Accept and verify `code_challenge` (S256 only, reject `plain`). Stash it in the Redis code payload, require a matching `code_verifier` at `/oauth/token`.

### S-CEN-008 — `oauth_redirect_uri` in env vars not in DB → not auditable
- **Severity**: LOW
- **File**: `packages/central/src/monctl_central/auth/oauth.py:88-95`; `config.py:104-112`
- **Description**: Exact-match validation is correct (no wildcard, no scheme coercion). However, `MONCTL_OAUTH_REDIRECT_URIS` is a comma-separated env var. There's no automated audit / drift detection for this list. None of the OAuth client configuration changes hit the audit log.
- **Fix sketch**: Move OAuth client config from env vars to a DB table (`oauth_clients` with `redirect_uris JSONB`). Surface in audit; require admin role to mutate.

### S-CEN-009 — Audit middleware blindly trusts `X-Forwarded-For` for client IP
- **Severity**: MED
- **File**: `packages/central/src/monctl_central/audit/request_helpers.py:8-19`
- **Description**: `get_client_ip` reads `X-Forwarded-For` first and trusts the first IP. If a customer exposes central directly (port 8443 on a public NIC), an attacker can spoof their source IP for every audit row.
- **Fix sketch**: Trust `X-Forwarded-For` only when `request.client.host` is in the configured proxy whitelist (`settings.trusted_proxies`); otherwise fall through to `request.client.host`.

### S-CEN-010 — Action automations execute arbitrary Python on central with `automation:create` permission
- **Severity**: HIGH
- **File**: `packages/central/src/monctl_central/automations/executor.py:60-130`, called from `automations/engine.py:418-423`
- **Description**: `target=central` actions run user-authored Python via `subprocess_exec("python3", script_path)` in a tempdir on the central node, with `os.environ.copy()` as the env (so `MONCTL_ENCRYPTION_KEY`, `MONCTL_JWT_SECRET_KEY`, DB DSN with password are inherited). Anyone with `automation:create` can author a script that exfils the encryption key + DB DSN and pivots the entire cluster.
- **Fix sketch**: Default `target=collector` for new actions; require admin (not just `automation:create`) for `target=central`. Strip secrets from the env. Run the subprocess inside a non-root container with no MonCTL secrets bind-mounted.

### S-CEN-011 — Superset OAuth token leak risk in central's logs
- **Severity**: LOW
- **File**: `packages/central/src/monctl_central/auth/oauth.py:282-405`
- **Description**: The `/v1/oauth/token` endpoint returns the new access_token in JSON. If FastAPI's request/response logging is ever turned on at DEBUG, the JSON body lands in central's logs and gets shipped to ClickHouse via the log pipeline. No code currently logs response bodies, but one careless `logger.debug("token response %s", resp)` in the future mints a token leak.
- **Fix sketch**: Add a structlog `processors.add_log_level + redact_keys=["access_token", "refresh_token", "id_token", "client_secret"]` filter to the central logging config so future debug code can't accidentally leak.

### S-CEN-012 — `_create_id_token` uses HS256 with the same secret as the access token
- **Severity**: LOW
- **File**: `packages/central/src/monctl_central/auth/oauth.py:168-186`
- **Description**: The ID token is HS256-signed with `settings.jwt_secret_key`. Anyone the secret is shared with can mint fresh ID tokens for any user. For external OIDC clients the OAuth provider would need to give them the secret, which is a non-starter. Documented but should be tracked.
- **Fix sketch**: Document blocked status. Plan RS256 + JWKS endpoint at `/v1/oauth/jwks.json` for the next external-client integration.

### S-CEN-013 — `decode_token` exception handler in `userinfo` swallows everything as `invalid_token`
- **Severity**: LOW
- **File**: `packages/central/src/monctl_central/auth/oauth.py:431-437`
- **Description**: `try: payload = decode_token(tok); except Exception:` returns `invalid_token`. A DB outage, a missing key, an unrelated import error all surface as `401 invalid_token`, hiding real problems.
- **Fix sketch**: Catch `jwt.InvalidTokenError` / `jwt.ExpiredSignatureError` / `jwt.PyJWTError` only; let everything else 500.

### S-CEN-014 — `_consume_code` falls back to non-atomic GET+DELETE on Redis < 6.2
- **Severity**: INFO
- **File**: `packages/central/src/monctl_central/auth/oauth.py:120-128`
- **Description**: If `GETDEL` is unsupported, the fallback `GET + DELETE` allows two concurrent OAuth clients to each redeem the same code. MonCTL ships Redis 7-alpine via the installer so the fallback never executes in practice.
- **Fix sketch**: Drop the fallback. Require Redis ≥ 6.2 explicitly; add a startup check.

### S-CEN-015 — `_set_tenant_scope_from_auth` defaults to fail-open
- **Severity**: LOW
- **File**: `packages/central/src/monctl_central/dependencies.py:53-73`
- **Description**: `tenant_scope_var` defaults to `""` — meaning the ClickHouse row policy short-circuits to "see everything". Background tasks / scheduler / startup code rely on this. Any future endpoint that reads from CH without going through a `Depends(require_*)` chain silently gains full-tenant visibility.
- **Fix sketch**: Default to `_NULL_TENANT_SENTINEL` (see-nothing). System code that legitimately needs full visibility sets the var explicitly to `""` at the entry point. Fail-open opt-in and visible.

### S-CEN-016 — Severity engine `aid_list` SQL string interpolation: drift risk
- **Severity**: LOW
- **File**: `packages/central/src/monctl_central/alerting/engine.py:535-538`
- **Description**: `aid_list = ", ".join(f"'{aid}'" for aid in assignment_ids)` interpolates UUIDs as SQL string literals. UUIDs are constrained to `[0-9a-f-]` so today this is safe. A future migration (e.g. introducing a non-UUID synthetic ID) would silently turn this into SQL injection.
- **Fix sketch**: Use ClickHouse's `IN ({aids:Array(UUID)})` parameter binding instead. Push the assignment_ids list into the existing `params` dict.

### S-CEN-017 — OAuth `_validate_redirect_uri` doesn't normalise — case-sensitive trailing slash mismatch
- **Severity**: INFO
- **File**: `packages/central/src/monctl_central/auth/oauth.py:88-95`
- **Description**: Exact-match is correct security-wise but bites operators: trailing slash mismatch ⇒ `400 invalid redirect_uri`.
- **Fix sketch**: Log the mismatch on the server side at INFO with both values so support can debug from logs. Don't change the user-facing 400.

### S-CEN-018 — `api_keys` mutation is unaudited
- **Severity**: MED
- **File**: `packages/central/src/monctl_central/audit/resource_map.py`; `tests/unit/test_audit_resource_map_coverage.py:39` (opt-out)
- **Description**: `api_keys` is in `_AUDIT_OPT_OUT` with the rationale "issuance already surfaces via collector registration / user key endpoints". But INSERT/UPDATE/DELETE on `api_keys` does not mutate the parent collector or user row, so the SQLAlchemy `before_flush` hook fires nothing. Issuing a long-lived management API key creates no audit row anywhere.
- **Fix sketch**: Move `api_keys` from `_AUDIT_OPT_OUT` into `TABLE_TO_RESOURCE` (label: `"api_key"`). Verify `redact_dict` redacts `key_hash`.

### S-CEN-019 — `assignment_credential_overrides` audit gap
- **Severity**: MED
- **File**: `tests/unit/test_audit_resource_map_coverage.py:51` (opt-out)
- **Description**: Same shape as S-CEN-018: opted out as "edge of app_assignments — parent is audited", but updating only the override row leaves the parent `AppAssignment` untouched. A privileged user can rebind which credential a job uses without any audit trail. Credential rebinding is the highest-impact authorisation change.
- **Fix sketch**: Add to `TABLE_TO_RESOURCE` with label `"assignment_credential_override"`. Same for `assignment_connector_bindings` if the same gap applies.

---

## Collector

### S-COL-001 — `MONCTL_PEER_TOKEN` grandfathered "wide open if unset" still present
- **Severity**: MED
- **File**: `packages/collector/src/monctl_collector/peer/server.py:228-247`
- **Description**: The peer auth interceptor only attaches when the env var is non-empty. With it unset, the gRPC server is unauthenticated — anything in the collector host's Docker bridge network can speak to the cache-node and call `GetCredential`. Memory says it has rolled (per-host PEER_TOKEN provisioned). It's time.
- **Fix sketch**: Refuse to start if `MONCTL_PEER_TOKEN` is unset; emit a fatal error explaining how to provision.

### S-COL-002 — Customer installer ships the same `MONCTL_COLLECTOR_API_KEY` to every collector + sidecar
- **Severity**: MED
- **Files**: `packages/installer/src/monctl_installer/render/templates/compose/collector.yml.j2:13, 17, 45, 67`; `env/docker-stats.env.j2:4`
- **Description**: Every customer-deployed collector and every docker-stats sidecar uses `${MONCTL_COLLECTOR_API_KEY}` — a single shared secret across the fleet. The infra hardening done in #117/#118/#122 added per-collector API keys to central, but the customer installer doesn't provision them. A leaked key is fleet-wide credential exposure.
- **Fix sketch**: After `monctl_ctl deploy` brings central up, call `POST /v1/collectors/<id>/api-keys` per host and write the per-collector key into `/opt/monctl/collector/.env` on the matching host. Keep the shared secret as a one-time bootstrap fallback.

---

## Frontend / Cross-cutting

### S-WEB-001 — Superset iframe lacks `sandbox`
- **Severity**: LOW
- **File**: `packages/central/frontend/src/pages/SupersetPage.tsx:41`
- **Description**: `<iframe src="/bi/" title="Superset" />` has no `sandbox` attribute. Same-origin via HAProxy means an XSS in Superset (e.g. via a chart's saved Markdown content) can read MonCTL's cookies and DOM.
- **Fix sketch**: Add `sandbox="allow-scripts allow-forms allow-same-origin"` (Superset needs same-origin to talk to its own backend). Test that the embedded login flow + dashboard interactions still work.

### S-WEB-002 — `frame-ancestors` allows `'self'` plus the public origin — duplicate
- **Severity**: INFO
- **File**: `packages/installer/src/monctl_installer/render/templates/config/superset_config.py.j2:755-758`
- **Description**: `frame-ancestors: ['self', 'https://10.145.210.40']` is redundant when the public origin IS self.
- **Fix sketch**: Drop the env-var-based duplicate, leave just `'self'`.

### S-X-001 — `oauth_redirect_uris` and OAuth client_secret stored in env, not in DB → not auditable
- **Severity**: MED
- **Files**: `packages/central/src/monctl_central/config.py:104-112`; `packages/central/src/monctl_central/audit/resource_map.py` (no `oauth_clients` table)
- **Description**: Rotating or revoking a client requires a redeploy. None of these changes hit the audit log. SOC-2-blocking gap.
- **Fix sketch**: Add an `oauth_clients` table; add to `audit/resource_map.py`. Implement admin-only CRUD endpoints. Migration backfills the env-configured client.

### S-X-002 — Customer installer doesn't generate per-collector API keys; S-INST-003 + S-COL-002 together mean MITM + shared-secret defaults
- **Severity**: HIGH
- **File**: cross-cutting
- **Description**: A fresh customer install ships with (a) `MONCTL_VERIFY_SSL=false` on every collector, and (b) the same shared `MONCTL_COLLECTOR_API_KEY` across every collector and the docker-stats sidecar. An attacker on the customer's L2 network can MITM any collector→central link, capture the shared key, and authenticate as any collector. The internal network protections that MonCTL prod relies on are NOT a customer-controllable assumption.
- **Fix sketch**: Tackle as one initiative — `monctl_ctl deploy` post-step that (i) calls central to register each collector, (ii) writes per-host API keys into per-host `.env`, (iii) flips `MONCTL_VERIFY_SSL=true` once central's cert chain is provisioned to each host.

### S-X-003 — Audit map opt-out includes `incidents` / `alert_entities`; alerting state changes are off-record
- **Severity**: MED
- **File**: `packages/central/tests/unit/test_audit_resource_map_coverage.py:43-44`
- **Description**: `alert_entities` and `incidents` are explicitly opted out — fine for the per-cycle state ticks, but **manual** state changes (admin clicks "ack" or "silence" on an incident, ops force-resolves a fired alert) are also unrecorded. The audit log says nothing about who acknowledged what when — a SOC-2 gap.
- **Fix sketch**: Keep the auto-bookkeeping out of audit, but route admin-driven state mutations through a dedicated `audit_alert_actions` resource. Add explicit audit calls from those endpoint handlers.

### S-X-004 — Sentinel config copy-then-launch leaks the rendered `sentinel.conf` into `/tmp` mode 0644
- **Severity**: LOW
- **File**: `packages/installer/src/monctl_installer/render/templates/compose/redis.yml.j2:38-42`
- **Description**: `cp /etc/redis/sentinel-template.conf /tmp/sentinel.conf` inherits the source's mode (likely 0644). With S-INST-007 fixed, this leaks the auth password to anything reading `/tmp` inside the container.
- **Fix sketch**: `cp ... && chmod 0600 /tmp/sentinel.conf && redis-sentinel /tmp/sentinel.conf`.

### S-X-005 — Architectural test missing for "no raw SQL string interpolation"
- **Severity**: INFO
- **File**: see S-CEN-016
- **Description**: The codebase has one consistent style (parameterised CH queries) and one drift point (alerting engine `aid_list`). The next time someone uses this file as a template, they may copy the unsafe pattern.
- **Fix sketch**: Add `tests/unit/test_no_raw_sql_interpolation.py` that scans CH-query call sites and flags any `f"WHERE ... '{...}'"` pattern.

### S-X-006 — Superset Talisman `force_https=False` and `session_cookie_secure=False`
- **Severity**: MED
- **File**: `packages/installer/src/monctl_installer/render/templates/config/superset_config.py.j2:760-761`
- **Description**: Same shape as F-CEN-001 (now fixed for central). Superset's session cookie is emitted without the `Secure` flag. Modern browsers don't care under HAProxy (Set-Cookie's Secure flag is enforced based on the response back to the user), but if Superset is ever exposed directly on port 8088 to the LAN, the cookie travels cleartext.
- **Fix sketch**: Wire through the same `cookie_secure` env var that central uses; default `True`. Since Superset trusts ProxyFix headers, `session_cookie_secure=True` is correct under HAProxy.

### S-X-007 — `central` compose template binds 8443 publicly; HAProxy is the only TLS hop
- **Severity**: LOW
- **File**: `packages/installer/src/monctl_installer/render/templates/compose/central.yml.j2:6-7`
- **Description**: `ports: - "8443:8443"` binds central directly to all interfaces. The audit-IP-trust issue (S-CEN-009) and the WS query-param fallback (S-CEN-001) compound here.
- **Fix sketch**: Render as `"127.0.0.1:8443:8443"` when haproxy is co-located on the same host; only expose all-interfaces when haproxy is on a different host (and then prefer a private interface address).

### S-X-008 — `cookie_secure: bool = True` default in central is overridden to False for dev — no audit when flipped
- **Severity**: LOW
- **File**: `packages/central/src/monctl_central/config.py:81-83`
- **Description**: `MONCTL_COOKIE_SECURE=false` is a documented dev knob. There's no audit trail when a customer admin flips it.
- **Fix sketch**: Read `cookie_secure` at startup, log it via the system_health subsystem, expose through `/system/config` (admin-only).

### S-X-009 — `superset-init.sh` runs `pip install --no-cache-dir` from PyPI on every restart
- **Severity**: LOW
- **File**: `packages/installer/src/monctl_installer/render/templates/config/superset-init.sh.j2:14-15`
- **Description**: `--no-cache-dir` makes the install re-fetch from PyPI every container start. Combined with S-INST-006, this widens the supply-chain window.
- **Fix sketch**: Drop `--no-cache-dir`. Better: bake the requirements into a custom `Dockerfile` that extends `apache/superset:4.1.1`.

### S-X-010 — Superset `urllib.request.urlopen` to MonCTL central without cert verification when HTTPS
- **Severity**: LOW
- **File**: `packages/installer/src/monctl_installer/render/templates/config/superset_config.py.j2:246-251`
- **Description**: The tenant-scope refresh calls `_urlreq.urlopen(req, timeout=3)`. If a customer sets `MONCTL_INTERNAL_BASE=https://...` (sensible for internal TLS), urllib uses the system CA store. MonCTL ships self-signed certs by default — every refresh fails closed, operator's likely fix is to add `ssl._create_unverified_context()`.
- **Fix sketch**: Document `MONCTL_INTERNAL_BASE` semantics explicitly. Provide an `MONCTL_INTERNAL_CA_BUNDLE` env var that `urlopen` honours via a custom SSLContext.

---

**Coverage gaps for the next cycle**:
- Inventory loader / planner / validators (`packages/installer/src/monctl_installer/inventory/`) — yaml.safe_load is correct but Pydantic model validation needs its own pass.
- TLS certificate generation/rotation flow (`packages/central/src/monctl_central/tls/`) wasn't sampled.
- The `os_install_*` flow (PR #139) and Patroni switchover endpoint — admin-only but holds remote-execution-grade primitives.

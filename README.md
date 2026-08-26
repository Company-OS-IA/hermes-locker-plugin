# Hermes Locker

`Hermes Locker` is a standalone Hermes Secret Source plugin for Locker Secrets Manager. It resolves explicit `locker://lower_snake_case` references at startup into the active profile's in-memory secret scope.

## Security model

- Locker remains the source of truth for operational credentials.
- Configuration stores references only; never secret values.
- Resolution is explicit: each profile maps an environment variable to one Locker reference.
- The plugin uses Locker CLI with a minimal child environment, closed stdin, and a bounded timeout.
- It does not cache decrypted values in the plugin or write them to disk.
- A failed, invalid, or empty lookup contributes no secret values.
- Hermes owns precedence, provenance, profile isolation, and environment application.

## Quick start

### 1. Install the Locker CLI

Download the binary using the official instructions at **https://locker.io/secrets/download**.

📖 **Full CLI documentation:** https://support.locker.io/en/locker-secrets-manager/developer-tools/secrets-commands-cli

Do not pipe remote installer scripts into a shell. Confirm the installed binary with `locker --version`.

This release is validated against Locker CLI 2.0.13.

### 2. Configure access keys

Set the bootstrap credentials in your Hermes `.env` file using an operator-controlled editor, then restrict the file to its service account with mode `0600`. Never put credential values in shell history, `config.yaml`, or repositories.

Credential files are intentionally unsupported by this plugin because Hermes bootstrap credentials must remain scoped to the active profile.

### 3. Add secrets to Locker

Use the Locker web dashboard at **https://secrets.locker.io**. Avoid passing secret values as command-line arguments.

### 4. Install the Hermes plugin

```bash
hermes plugins install Company-OS-IA/hermes-locker-plugin --enable
```

### 5. Configure the profile mapping

Add to your profile's `config.yaml`:

```yaml
secrets:
  sources: [locker]
  locker:
    enabled: true
    override_existing: true
    timeout_seconds: 15
    env:
      MY_API_KEY: locker://my_api_key
      DATABASE_URL: locker://database_url
```

### 6. Validate and restart

```bash
hermes locker status
hermes locker status --probe-key my_api_key
hermes gateway restart
```

## Bootstrap and authentication

Locker itself needs a protected service identity. The gateway deployment must provide the Locker CLI bootstrap variables outside Hermes configuration:

- `LOCKER_ACCESS_KEY_ID`
- `LOCKER_ACCESS_KEY_SECRET`

Legacy `LOCKER_SECRET_ACCESS_KEY` is also accepted for compatibility. These are bootstrap credentials only; provider, MCP, and platform credentials belong in Locker.

The Locker CLI supports **access keys** (via environment variables, flags, or credential file). It does **not** expose an OAuth login flow. `Hermes Locker` reports OAuth as unsupported instead of attempting a fallback or presenting a non-functional option.

## Operator CLI

Use the operator CLI before enabling any profile mapping:

```bash
hermes locker status
hermes locker status --probe-key example_api_key
hermes locker setup --auth-mode access-keys
hermes locker setup --auth-mode credential-file
```

`status` never prints credential values. `setup` is guidance only: it never downloads installers, invokes remote scripts, writes credentials, or runs interactive authentication.

## Profile configuration

Use a mapped configuration in the specific profile that needs the credential:

```yaml
secrets:
  sources: [locker]
  locker:
    enabled: true
    override_existing: true
    timeout_seconds: 15
    env:
      EXAMPLE_API_KEY: locker://example_api_key
      SECONDARY_API_TOKEN: locker://secondary_api_token
```

Only lowercase snake case Locker references are accepted. A mapping is all-or-nothing: if any reference is invalid, unavailable, or empty, the plugin applies none of that profile's mapped secrets.

## Validation

```bash
PYTHONPATH=/usr/local/lib/hermes-agent python tests/test_locker_source.py -v
```

For a live isolated check, invoke `LockerSecretSource.fetch()` with a temporary home and one non-production mapping. Do not print `FetchResult.secrets`.

## Migration sequence

1. Install and validate on a non-production profile with one mapping.
2. Migrate one non-critical secret; validate it resolves correctly.
3. Migrate remaining secrets incrementally.
4. Remove process-inheritance allowlists and Locker wrapper.
5. Restart gateway and run full profile-isolation smoke tests.

Do not remove the existing bridge until all affected integrations pass after a gateway restart.

## Troubleshooting

| Symptom | Cause | Fix |
|---------|-------|-----|
| `locker CLI: missing` | Binary not on PATH | Install CLI to `/usr/local/bin` or add to PATH |
| `authentication probe: failed (unauthorized)` | Access-key pair rejected | Verify that ID and secret belong to the same access key |
| `authentication probe: failed (forbidden)` | Access key cannot read the requested secret | Grant read access to the project/secret |
| `Locker returned an empty mapped secret` | Key exists but has no value | Set value via CLI or dashboard |
| `Flag --secret-access-key has been deprecated` | Old CLI flag usage | Use `--secret-access-key-env` |

<!-- generated-by: gsd-doc-writer -->
# Hermes Locker

[English](README.md) | [Português (Brasil)](README.pt-BR.md)

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

Hermes Secret Source plugin that resolves explicit Locker Secrets Manager references into the active Hermes profile at startup.

## What it does

- Maps Hermes environment variables to `locker://lower_snake_case` references.
- Uses the active profile's bootstrap credentials, or an explicitly opted-in protected systemd credential for cold profile hydration (0.3.0).
- Sends only a minimal, ephemeral environment to the Locker CLI.
- Never prints resolved values or writes them to Hermes configuration.
- Applies a mapping as a single unit: if one lookup fails or is empty, none of that pass's values are returned.

The plugin does not maintain a Python cache or write decrypted values itself. The Locker CLI may maintain its own local data according to its implementation; `--refresh` is used for every plugin lookup to require a fresh Locker response.

## Requirements

- A Hermes installation with Secret Source plugin support.
- Locker CLI available on the gateway service account's `PATH`.
- A Locker access key with read permission for every mapped secret.

This release is validated against Locker CLI 2.0.13.

## Installation

### 1. Install the Locker CLI

Follow the official [Locker CLI download instructions](https://locker.io/secrets/download) and review the [Locker secrets command documentation](https://support.locker.io/en/locker-secrets-manager/developer-tools/secrets-commands-cli).

Do not pipe remote installer scripts into a shell. Verify the installed binary:

```bash
locker --version
```

Run this check as the same service account and inside the same container or runtime that starts Hermes. Installing the Locker CLI only on the host does not make it available inside a Hermes container.

### 2. Provision the Hermes bootstrap access key

Create a Locker access key with read access to the secrets Hermes will resolve. Do not pass its secret value through chat, command arguments, logs, or source control.

### 3. Provision protected bootstrap credentials

The only supported public input names are `LOCKER_ACCESS_KEY_ID` and `LOCKER_ACCESS_KEY_SECRET`. Provision the matching pair through a protected deployment mechanism; do not store plaintext bootstrap credentials in `.env`, `config.yaml`, repositories, agent workspaces, shell history, or conversations.

For a systemd gateway, provision an **encrypted systemd credential** named `locker_bootstrap_env`. Its decrypted UTF-8 payload must contain the two canonical `NAME=value` assignments, once each, with non-empty values. This is a strict assignment format, not a shell script: no `export`, comments, additional keys, or shell expansion. Supply the payload from a trusted secret-delivery process directly to `systemd-creds encrypt --with-key=host --name=locker_bootstrap_env - <encrypted-output-path>` over stdin; never put real values in arguments or a plaintext staging file. Restrict the encrypted source file to the service administrator (for example, root-owned mode `0600`).

Example service drop-in (the path is illustrative and contains only encrypted data):

```ini
[Service]
LoadCredentialEncrypted=locker_bootstrap_env:/etc/credstore.encrypted/locker_bootstrap_env
```

Systemd decrypts and materializes the credential for the service. The plugin reads it directly after the profile opts in below; no wrapper export or `EnvironmentFile=%d/locker_bootstrap_env` is needed. The process-level `CREDENTIALS_DIRECTORY` is only a **non-secret directory locator**, not a bootstrap identity or an authorization grant. Do not add bootstrap secrets to a global environment allowlist to make cold profiles work.

For standalone startup without this opt-in, the complete canonical pair must already be available in the active Secret Source environment through protected injection. Injecting it only into a shared gateway's process environment does **not** provision every cold multiplexed profile. See [bootstrap precedence](#bootstrap-authentication).

> `locker configure` remains optional for manual Locker CLI use. Its credential file is not read by the plugin; this is separate from the opt-in systemd credential above.

### 4. Add secrets to Locker

Create the required global secrets in the [Locker dashboard](https://secrets.locker.io). Avoid passing secret values as command-line arguments.

### 5. Install and enable the plugin

```bash
hermes plugins install Company-OS-IA/hermes-locker-plugin --enable
```

For a reproducible production installation, add `--ref` with a reviewed 40-character commit SHA.

### 6. Configure the active Hermes profile

Add explicit mappings to the profile's `config.yaml`:

```yaml
secrets:
  locker:
    enabled: true
    bootstrap_credential: locker_bootstrap_env
    override_existing: true
    timeout_seconds: 45
    env:
      MY_API_KEY: locker://my_api_key
      DATABASE_URL: locker://database_url
```

`bootstrap_credential` is an **opt-in**, not a default. Include it only in profiles authorized to use the service's shared Locker identity; omit it when using a profile-specific bootstrap pair. It accepts a lower_snake_case basename (at most 128 characters), never a path or secret value. Install/enable the plugin and configure mappings in each profile that needs it.

`secrets.sources` is optional and is not an allowlist. For a Locker-only setup, omit it as shown above: `enabled: true` is sufficient after plugin discovery. Enabled sources omitted from the list are still appended; use an explicit list only when ordering multiple Secret Sources matters. Some Hermes versions validate that list before standalone plugins are discovered and may otherwise print a transient `unknown source(s): locker` warning.

`timeout_seconds` is the total wall-clock budget for the complete mapping pass. The plugin default is 15 seconds; use a larger value when resolving several remote secrets or when the Locker API has higher latency.

`cache_ttl_seconds` is not a Locker plugin setting. Remove it from inherited configurations: the plugin intentionally keeps no Python cache and uses `--refresh` for every lookup.

### 7. Validate and restart

For standalone CLI diagnostics, use a protected environment containing the canonical pair (do not export values through shell history):

```bash
hermes plugins show hermes-locker
hermes locker status
hermes locker status --probe-key my_api_key
hermes gateway restart
hermes gateway status
```

The probe retrieves the selected value but discards it without printing it. `hermes locker status` reads its own process environment; it does not read `bootstrap_credential` or exercise cold profile hydration. A passing CLI probe is **not proof of cold multiplex bootstrap**; missing CLI keys can also coexist with a correctly provisioned systemd credential.

After changing the service drop-in, reload the appropriate systemd manager before restarting. Verify a fresh gateway process with cold profile scopes: each opted-in profile must receive only its configured mapped names, a profile without a pair or opt-in must receive none from Locker, and the dependent integration must pass a read-only check. Inspect status, provenance and variable names only, never values. Hermes can memoize failed hydration per home; restart or use an approved cache reset before retesting a corrected configuration.

## Configuration reference

| Setting | Required | Default | Description |
|---|---:|---:|---|
| `enabled` | Yes | `false` | Enables Locker resolution for the profile. |
| `env` | Yes | `{}` | Explicit Hermes environment-variable to `locker://key` mappings. |
| `bootstrap_credential` | No | Unset | Opt-in basename of a protected systemd credential, e.g. `locker_bootstrap_env`. |
| `override_existing` | No | `true` | Lets Locker replace stale shell or `.env` values for mapped variables. |
| `timeout_seconds` | No | `15` | Total wall-clock budget for one complete fetch pass. |

Environment-variable names must match `[A-Z][A-Z0-9_]*`. Locker references must use lowercase snake case and contain at most 128 characters, for example `locker://database_url`.

## Bootstrap authentication

| Variable | Required | Purpose |
|---|---:|---|
| `LOCKER_ACCESS_KEY_ID` | Yes | Identifies the Locker access key used by the active profile. |
| `LOCKER_ACCESS_KEY_SECRET` | Yes | Canonical input for the matching secret; forwarded only through the subprocess environment. |

These are the only supported plugin-input names, whether supplied in the profile's Secret Source environment or the systemd payload. For Locker CLI wire compatibility, the plugin translates `LOCKER_ACCESS_KEY_SECRET` to `LOCKER_SECRET_ACCESS_KEY` **only in the child process environment**, for both fetches and CLI probes. `LOCKER_SECRET_ACCESS_KEY` is **not a supported plugin-input alias**; do not provision it in the profile or credential payload.

### Cold profile precedence and isolation

Hermes cold multiplex hydration supplies a private environment for each profile, rather than inheriting arbitrary secrets from the gateway process. The plugin uses `get_source_environment()`:

1. A complete, valid canonical profile pair wins; the systemd credential is not opened.
2. If either canonical name exists but the pair is partial or invalid (including blank, non-string, NUL or newline-containing values), resolution fails closed. It never mixes profile and service identities or falls back to the shared pair.
3. Only when **both names are absent** and `secrets.locker.bootstrap_credential` is explicitly set does the plugin read that credential under the process's `CREDENTIALS_DIRECTORY`.
4. Without either a valid pair or the opt-in credential, no Locker values are returned. There is no process-global secret fallback or new global secret allowlist for cold hydration. Outside a scoped fetch, Hermes may expose the process environment as the source environment; this is why standalone success is insufficient.

The plugin neither mutates `os.environ` nor adds bootstrap values to resolved mappings. Each profile receives only its explicit `env` mappings through Hermes' per-home hydration and `secret_scope`. **Sharing a service identity is not distinct vault ACLs:** all opted-in profiles use the same Locker access key and its read permissions. Mappings isolate normal hydration output, not vault authorization against a profile able to change its mappings or execute code as the service account. Use distinct least-privilege identities and separate service/OS boundaries when independent vault authorization is required.

### Protected credential reads

The credential directory must be absolute, without empty, `.` or `..` components. Descriptor-relative traversal uses no-follow opens for every directory component and the file. Owners must be root or the effective service UID; ancestors cannot be group/world writable except for root-owned sticky parents. The final directory must deny all group/other access. The file must be regular, non-executable and inaccessible to group/other (typically `0400` or `0600`), with both its reported size and bounded read limited to 16,384 bytes. Symlinks, unsafe modes/owners, special files, oversized data, malformed UTF-8, duplicate/unknown keys and incomplete/invalid pairs fail closed with no mapped values. Platforms without the required secure-open flags also fail closed.

The plugin rereads the credential on each fetch; Hermes' per-home hydration cache is separate. OAuth and credential files created by `locker configure` remain unsupported for startup; the protected systemd mechanism is the explicit exception for file-based bootstrap delivery.

## Operator commands

```bash
hermes locker setup --auth-mode access-keys
hermes locker status
hermes locker status --probe-key example_api_key
```

These commands never install software, write credentials, run interactive authentication, or print resolved secret values.

## Current limitations

- Only explicit mapped references are supported; bulk import is not.
- Locker environment selection is not exposed yet. Lookups use Locker's global secret behavior.
- Credential files created by `locker configure` are not used for Hermes startup.
- Fetches are sequential and share the configured total timeout budget.

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `unknown source(s): locker` | `secrets.sources` was validated before standalone plugin discovery. | Omit the optional `sources` list when Locker is the only source. If Locker is not applied afterward, update Hermes and confirm the plugin is enabled in the same profile. |
| `locker CLI: missing` | Binary is not available in the gateway's user/container runtime or `PATH`. | Install the Locker CLI in that same runtime or correct the service `PATH`. |
| `bootstrap access keys not configured` | One or both bootstrap variables are missing from the active source environment. | Provision the complete pair through protected injection, or opt the cold profile into a protected systemd credential, then restart. |
| `Locker service bootstrap credential is unavailable or invalid` | Opt-in credential cannot be read safely or its payload is invalid. | Check the basename, service `LoadCredentialEncrypted`, locator, ownership/modes and canonical payload without printing values. |
| `Locker bootstrap identity is incomplete or invalid` | A profile bootstrap field is invalid; a partial pair also blocks fallback. | Correct the complete profile pair through protected provisioning; do not expect shared-identity fallback. |
| CLI probe passes but cold profile resolution fails | CLI process credentials do not prove per-profile hydration. | Check plugin discovery, profile opt-in/mappings and the service credential in a fresh gateway process; do not globally allowlist secrets. |
| `authentication probe: failed (invalid_access_key_id)` | Locker does not recognize the supplied access-key ID. | Verify or recreate the Locker access key and update the gateway environment. |
| `authentication probe: failed (unauthorized)` | The ID/secret pair is rejected or does not match. | Provision the matching pair together and restart the gateway. |
| `authentication probe: failed (forbidden)` | Authentication succeeded but the key cannot read the requested secret. | Grant the access key read permission for that secret or project. |
| `fetch exceeded ... budget` | The complete mapping pass exceeded `timeout_seconds`. | Increase `secrets.locker.timeout_seconds` and check Locker/network latency. |
| `Locker returned an empty mapped secret` | The key exists but its value is empty. | Set a non-empty value in Locker. |

## Development validation

Run from a clone with Hermes Agent and pytest available:

```bash
env -i PATH="$PWD/.venv/bin:/usr/local/bin:/usr/bin:/bin" \
    HOME=/nonexistent \
    PYTHONPATH=/usr/local/lib/hermes-agent \
    python -B -m pytest -q -p no:cacheprovider

hermes plugins doctor --ci
git diff --check
```

Adjust only the interpreter `PATH` and Hermes source `PYTHONPATH` for your installation. `env -i` starts the test process with only these minimal `PATH`, `HOME` and `PYTHONPATH` entries: no inherited credentials or `CREDENTIALS_DIRECTORY`. The suite creates synthetic credentials and mocked Locker responses; it covers protected reads, precedence and cold hydration/profile isolation without live Locker access. Never supply real credentials to tests. Plugin doctor is a separate discovery/conformance check, not proof of live cold multiplex bootstrap.

## License

Released under the [MIT License](LICENSE).

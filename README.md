<!-- generated-by: gsd-doc-writer -->
# Hermes Locker

[English](README.md) | [Português (Brasil)](README.pt-BR.md)

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

Hermes Secret Source plugin that resolves explicit Locker Secrets Manager references into the active Hermes profile at startup.

## What it does

- Maps Hermes environment variables to `locker://lower_snake_case` references.
- Uses the active profile's bootstrap credentials instead of process-global cached values.
- Sends only a minimal, ephemeral environment to the Locker CLI.
- Never prints resolved values or writes them to Hermes configuration.
- Applies a mapping as a single unit: if one lookup fails or is empty, none of that pass's values are returned.
- Supports the legacy `LOCKER_SECRET_ACCESS_KEY` name by normalizing it only inside the Locker subprocess environment.

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

### 2. Provision the Hermes bootstrap access key

Create a Locker access key with read access to the secrets Hermes will resolve. Do not pass its secret value through chat, command arguments, logs, or source control.

### 3. Add the bootstrap variables to Hermes

The gateway process must receive both bootstrap variables before the plugin is enabled:

```dotenv
LOCKER_ACCESS_KEY_ID=your_access_key_id
LOCKER_ACCESS_KEY_SECRET=your_secret_access_key
```

For a standard installation, place them in the active Hermes profile's `.env` file:

```text
~/.hermes/.env
```

Examples:

- A gateway running as `root` uses `/root/.hermes/.env`.
- A gateway running as another service user uses that user's `~/.hermes/.env`.
- A named Hermes profile uses its active `HERMES_HOME/.env`.

Open the file with an operator-controlled editor, add the two variables, and restrict it to the gateway service account:

```bash
chmod 600 ~/.hermes/.env
```

Do not put these values in `config.yaml`, plugin configuration, repositories, shell history, or agent conversations. An installation agent should verify only that both variable names are present. If either is absent, it must ask the operator to provision it without reading or printing the value.

Systemd `EnvironmentFile`, container secrets, and hosting-platform secret stores are also valid when they inject both variables into the gateway process.

> `locker configure` is optional for manual Locker CLI use. Its credential file is intentionally not used by this plugin; Hermes still requires the two variables above in its protected environment.

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
  sources: [locker]
  locker:
    enabled: true
    override_existing: true
    timeout_seconds: 45
    env:
      MY_API_KEY: locker://my_api_key
      DATABASE_URL: locker://database_url
```

`timeout_seconds` is the total wall-clock budget for the complete mapping pass. The plugin default is 15 seconds; use a larger value when resolving several remote secrets or when the Locker API has higher latency.

### 7. Validate and restart

Run the probe from an environment that loads the same active Hermes `.env`:

```bash
hermes plugins show hermes-locker
hermes locker status
hermes locker status --probe-key my_api_key
hermes gateway restart
hermes gateway status
```

The probe retrieves the selected value but discards it without printing it.

## Configuration reference

| Setting | Required | Default | Description |
|---|---:|---:|---|
| `enabled` | Yes | `false` | Enables Locker resolution for the profile. |
| `env` | Yes | `{}` | Explicit Hermes environment-variable to `locker://key` mappings. |
| `override_existing` | No | `true` | Lets Locker replace stale shell or `.env` values for mapped variables. |
| `timeout_seconds` | No | `15` | Total wall-clock budget for one complete fetch pass. |

Environment-variable names must match `[A-Z][A-Z0-9_]*`. Locker references must use lowercase snake case and contain at most 128 characters, for example `locker://database_url`.

## Bootstrap authentication

| Variable | Required | Purpose |
|---|---:|---|
| `LOCKER_ACCESS_KEY_ID` | Yes | Identifies the Locker access key used by the active profile. |
| `LOCKER_ACCESS_KEY_SECRET` | Yes | Supplies the matching secret only through the subprocess environment. |
| `LOCKER_SECRET_ACCESS_KEY` | Legacy only | Accepted as an older spelling and normalized ephemerally. |

The Locker CLI itself supports flags and credential files, but the plugin deliberately requires profile-scoped environment bootstrap credentials. OAuth and credential-file startup modes are not supported by this plugin.

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
| `locker CLI: missing` | Binary is not on the gateway service account's `PATH`. | Install the Locker CLI or correct the service `PATH`. |
| `bootstrap access keys not configured` | One or both bootstrap variables are missing from the active Hermes environment. | Add both variables to the active profile `.env` or protected service environment, then restart. |
| `authentication probe: failed (invalid_access_key_id)` | Locker does not recognize the supplied access-key ID. | Verify or recreate the Locker access key and update the gateway environment. |
| `authentication probe: failed (unauthorized)` | The ID/secret pair is rejected or does not match. | Provision the matching pair together and restart the gateway. |
| `authentication probe: failed (forbidden)` | Authentication succeeded but the key cannot read the requested secret. | Grant the access key read permission for that secret or project. |
| `fetch exceeded ... budget` | The complete mapping pass exceeded `timeout_seconds`. | Increase `secrets.locker.timeout_seconds` and check Locker/network latency. |
| `Locker returned an empty mapped secret` | The key exists but its value is empty. | Set a non-empty value in Locker. |

## Development validation

Run from a clone with Hermes Agent and pytest available:

```bash
env -u LOCKER_ACCESS_KEY_ID \
    -u LOCKER_ACCESS_KEY_SECRET \
    -u LOCKER_SECRET_ACCESS_KEY \
    PYTHONPATH=/usr/local/lib/hermes-agent \
    python -m pytest -q

hermes plugins doctor --ci
git diff --check
```

The tests use synthetic values and clear all three Locker bootstrap variables for each case. Never use production credentials in the test suite.

## License

Released under the [MIT License](LICENSE).

# Public repository hardening / producer-signer setup

Repository: `mozzibara/auto-daangn`. This is a **one-time operator procedure**,
not an assertion that privileged GitHub settings or any secret have been set.
No live marketplace capture, OCI installation or Telegram delivery is performed.

## 0. Ownership and source preflight

Use only the `mozzibara` GitHub account with admin access. The repository must
remain Public, with the reviewed `main` source; do not move the private legacy
history into this repository. Confirm the current successful offline CI at
[Actions](https://github.com/mozzibara/auto-daangn/actions).

The current pinned **public** Ed25519 verifier SHA-256 is:

```text
54473a7acab59b546030d1115f03213c4b6ad7128a902206ef94439d117557e6
```

Only an existing matching 32-byte signer seed (44-character base64 file)
is accepted. **Do not copy a seed or GitHub token into Issues, PRs, chat,
commit history or Actions dispatch inputs.** If the original private seed
is unavailable, stop and run a **separate** planned key rotation, including
the OCI pinned verifier. Do not invent or upload an unrelated new key.

## 1. GitHub Actions policy

Open `Settings > Actions > General` at
https://github.com/mozzibara/auto-daangn/settings/actions

- Enable Actions; allow **GitHub-created actions and reusable workflows**.
  The repository currently uses `actions/checkout`,
  `actions/setup-python` and `actions/upload-artifact`.
- Set default `GITHUB_TOKEN` permissions to **Read repository contents and
  packages permissions** (read-only).
- Disable **Allow GitHub Actions to create and approve pull requests**.
- In **Approval for running fork pull request workflows from contributors**,
  select the most restrictive available option that requires approval for
  all external contributors. Never approve unfamiliar workflow changes without
  reviewing their content.

Existing workflow YAML already explicitly specifies `permissions: contents: read`.
Settings still provide a second defense-in-depth layer.

## 2. Protect main via a repository branch ruleset

Open `Settings > Rules > Rulesets` at
https://github.com/mozzibara/auto-daangn/settings/rules

Create **New branch ruleset**:

- Name: `main-protected-solo-ci`; enforcement **Active**.
- Target branches: **main** only.
- No bypass actors (including administrators).
- **Restrict deletions**: enabled.
- **Block force pushes**: enabled.
- **Require linear history**: enabled. Use squash/rebase merges.
- **Require a pull request before merging**: enabled. Required approving
  reviews: **0** for a solo owner. Require conversation resolution.
  Do not enable Code Owners or last-push approvals unless an independent
  reviewer is available.
- **Require status checks to pass**: enabled. Require the **exact job names**
  `Python 3.13 / ubuntu-latest` and `Python 3.13 / windows-latest`.
  Require branches to be up to date before merging.
- Do **not** require separate OCI path-filtered jobs globally: on unrelated
  README-only PRs they may be skipped and cause a permanent merge block.

The equivalent API request body is checked into
`ops/github/main-ruleset.json`. If GitHub CLI is authenticated as
`mozzibara`, the **single-create** command below creates the ruleset:

```powershell
gh api user --jq .login
gh api --method POST repos/mozzibara/auto-daangn/rulesets --input ops/github/main-ruleset.json
```

Run this only if no equivalent ruleset already exists; repeat POST creates
duplicates. API creation requires repository Administration write permission.
Verify after saving with
`gh api repos/mozzibara/auto-daangn/rulesets`.
Do not add a blanket admin bypass to resolve an unrelated CI failure.

## 3. Configure the signer-scoped environment

Open `Settings > Environments`:
https://github.com/mozzibara/auto-daangn/settings/environments

- Create environment **`daangn-producer`**.
- Under **Deployment branches and tags**, choose **Selected branches and tags**.
- Add **Branch** exactly `main` and **no tags**. Do not choose
  **Protected branches only**: that option may permit all branches when no
  branch protection rule exists.
- For a single-operator account leave **Required reviewers** unset: requiring
  the same operator to approve their own deployment could deadlock. The live
  job already requires exact owner authorization; the environment restricts
  the signing secret to owner-controlled main workflow code.
- Under **Environment secrets**, add the exact name
  `V434_ATTEST_ED25519_KEY_B64`.
- Never add this value as a repository-level secret; the environment secret
  is intentionally narrower.

GitHub environment secrets are available only to jobs explicitly requesting
the environment, and deployment branch policies constrain those jobs. Both
`.github/workflows/verify-v434-signer.yml` and the manually approved
`secure-links-v434.yml` request `daangn-producer`.

## 4. Verify the original seed *locally*, then upload directly to GitHub

From an owner-controlled Windows PowerShell terminal in a checked-out copy
of this **public** repository (after the environment-gate code is merged),
with Python `cryptography` already installed:

```powershell
$repo = 'mozzibara/auto-daangn'
$secretFile = 'C:\FULL\PRIVATE\PATH\ed25519_signer_secret_b64.txt'

# Only validate locally; this prints a pass code and public key fingerprint.
python -m scripts.verify_github_signer --local-secret-file $secretFile
if ($LASTEXITCODE -ne 0) { throw 'SIGNER_PUBLIC_KEY_MISMATCH_STOP' }

# Require the correct GitHub CLI identity before writing any secrets.
$login = gh api user --jq .login
if ($LASTEXITCODE -ne 0 -or $login.Trim() -ne 'mozzibara') {
    throw 'WRONG_GITHUB_ACCOUNT_STOP'
}

# Secret value is streamed from local file directly to GitHub.
# It is not printed or placed on the command line as an argument.
Get-Content -LiteralPath $secretFile -Raw -Encoding UTF8 |
    gh secret set V434_ATTEST_ED25519_KEY_B64 --repo $repo --env daangn-producer
if ($LASTEXITCODE -ne 0) { throw 'SECRET_UPLOAD_FAILED' }

# This prints names / metadata only, not secret values.
gh secret list --repo $repo --env daangn-producer
```

If the owner has the original private repository checkout, the generated
seed file was originally named
`local_private/v434-signer/ed25519_signer_secret_b64.txt`
inside the *local, ignored* working tree. That is a possible location, not
proof that the file exists now. Keep the recovery copy offline.

Alternative: use **GitHub Settings > Environments > daangn-producer >
Environment secrets > Add secret**; paste locally without showing it in
chat, screenshares or a public shell transcript.

## 5. One-time offline verifier (no marketplace visit)

From the `mozzibara` account, start the **manual**
`Verify configured v4.34 Ed25519 signer (no live capture)`
workflow at
https://github.com/mozzibara/auto-daangn/actions/workflows/verify-v434-signer.yml

Or use:

```powershell
gh workflow run verify-v434-signer.yml --repo mozzibara/auto-daangn --ref main
```

Pass condition: job log contains `V434_ED25519_SIGNER_PUBLIC_KEY_MATCH`.
No live capture, Telegram delivery or OCI import occurs here. Missing secret,
invalid key, unmatched public fingerprint or non-owner actor must fail closed.

## 6. Production gate

Do **not** run `secure-links-v434.yml` or turn on OCI intake timers until:

1. Ruleset is active and both required CI checks are green.
2. `daangn-producer` has **only main** in deployment branches.
3. The Environment Secret is configured and the manual verifier succeeds.
4. A signed dry-run succeeds and the existing OCI `/var/lib/auto-daangn` private state and key fingerprints are verified. **Backups are disabled by explicit owner choice**; no offsite receipt is required. This accepts the possibility of irreversible data loss.

The signing key remains private; the public verifier in source is not itself
a secret. Future key rotation is a multi-component migration, not merely
replacing one GitHub secret.

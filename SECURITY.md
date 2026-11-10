# Security policy

This repository contains public source and synthetic tests only. It must not contain GitHub tokens, OCI API keys/OCIDs for private resources, private Ed25519/X25519 keys, GitHub Actions signing secrets, Telegram bot credentials, browser sessions, cookies, passwords, live listing exports, original listing URLs or a persistent SQLite database.

Live collection is bounded, read-only and owner-approved. Do not bypass site access controls, ignore robots.txt, or treat signed captures as verified sale availability.

**Pull requests:** Only offline tests run from untrusted pull requests. Do not introduce `pull_request_target` with checkout of untrusted code or grant write/secret access to pull-request jobs.

**Capture signing:** Only the trusted owner-approved `main` workflow may access the optional Ed25519 signer Secret. Treat any exposure as a key-rotation incident. OCI must verify the independently pinned public key, exact producer repository/workflow, run identity, expected commit and ciphertext before import.

**Credentials:** Configure secrets out of band and with least privilege. Never submit private credentials in an issue, pull request or support chat. No live secrets were migrated from the previous private repository.

**Disclosure:** Report security issues privately through GitHub's private vulnerability reporting feature when enabled. Do not post exploit details or secrets publicly.

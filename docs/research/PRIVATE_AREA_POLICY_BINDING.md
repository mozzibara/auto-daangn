# Explicit private area policy binding

Opt-in v2 area policies are revalidated and normalized before use. The
canonical policy digest is inside the encrypted manifest only. Producer,
private renderer, advisory and authenticated importer require the same
explicit policy. A policy change, missing policy, absent location witness
or unknown/null label fails closed. The existing v1 default and legacy
manifests remain supported only when no explicit v2 policy is supplied.

The existing attestation authenticates the ciphertext; the policy digest
therefore travels within the authenticated payload, not a new public
summary field. No actual owner region or ID is published.

This is the offline boundary only. Live Route selection, actual coverage
discovery, configuration delivery to the producer and receiver, trusted
policy version lifecycle and search intent remain to be integrated before
real v2 captures. No live permission or production configuration changes.

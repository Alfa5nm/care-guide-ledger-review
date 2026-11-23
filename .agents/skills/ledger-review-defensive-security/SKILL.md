---
name: ledger-review-defensive-security
description: Review Ledger Review changes that touch Railway configuration, authentication, upload limits, document parsing, persistence, or outbound data for insecure defaults and verify the expected controls in project tests.
---

# Ledger Review defensive security

Use the trust boundaries in docs/SECURITY.md. Review actual callers and production defaults before changing a control. Read the Railway start script, deployment configuration, application boundary, and worker environment when a finding depends on deployment settings. Treat a missing configuration value as a separate case from an explicitly configured value.

Check that hosted startup fails closed without a strong reviewer secret and without a persistent volume. Confirm that protected routes check the reviewer credential before reading a body, browser writes use the canonical origin, stored names are generated, and hosted worker inputs exclude credentials and model endpoint settings. Trace job and correction state changes through their transactions.

Use synthetic fixtures and unit or acceptance tests that assert denied access, bounded input, or safe state transitions through supported interfaces. Record which settings and behaviors were actually checked, the affected file and line, and the remaining assumptions. Read the repository and deployed application within the scope of the user's request.

For each suspected insecure default, follow the value to the actual decision, then try to disprove the finding with a stricter inherited setting, a startup failure, or a limited caller contract. Keep the review sequential and use existing unit and acceptance commands.

The fail-closed review method adapts the [Trail of Bits Claude Code command](https://github.com/trailofbits/skills/blob/149d7b21f4067765b82e67029730b42d228ef4b4/plugins/insecure-defaults/commands/audit.md) under [CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/). This adaptation also uses the [OpenAI threat modeling reference](https://github.com/openai/codex-security/blob/main/plugins/codex-security/references/threat-model.md).

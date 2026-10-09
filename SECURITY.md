# Security

## Reporting a problem
Please report security issues privately through GitHub's "Report a vulnerability" (Security tab) rather than a public issue.

## How secrets are handled
- No secrets live in this repository. `.env.example` holds placeholders only; `.env` is git-ignored.
- Secrets (LLM API key, Discord bot token) are read from environment variables only. `Settings` hides them from `repr()`, and LLM errors never include request headers.
- Every push and pull request runs [gitleaks](https://github.com/gitleaks/gitleaks) plus `scripts/check-secrets.sh` (private IP ranges, personal email domains, token shapes, Discord-style IDs). Run `make scan` before pushing.

## Safety defaults
- `SEND_ENABLED=false` by default: approved items are recorded as a dry run and nothing is delivered.
- `APPROVER_USER_IDS` is empty by default, and `haa run` refuses to start until it is set.
- Approval is checked by user ID, never by display name.
- The sender verifies the SHA-256 of the text against the hash recorded at approval time and refuses to send on mismatch.
- Commands per user per minute and sends per hour are rate limited.
- The audit log is append-only JSONL with a hash chain (`haa verify-audit`).

## Deployment notes
- Give the Discord bot access to one private channel only, with "Read Messages", "Send Messages" and "Attach Files". It needs the Message Content intent.
- Run the container as the non-root user the image creates; it opens no ports.
- Back up `data/` (SQLite and audit log). Ship `audit.jsonl` to write-once storage if you need it to be tamper-proof rather than tamper-evident.
- Prompt injection: incoming messages are untrusted text and go into the Drafter's prompt. The Reviewer and the human gate are the controls; the Drafter has no tools and cannot send anything itself.

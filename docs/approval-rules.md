# Approval rules

Agents may draft anything. Nothing goes out unless a person on the allowlist explicitly approves that exact version. These rules are enforced in `approval/gate.py`, `state_machine.py` and `senders.py`, and each one has tests in `tests/test_approval_gate.py`.

## The rules

1. **Only allowlisted user IDs count.** `APPROVER_USER_IDS` holds Discord user IDs (or the CLI identity). Display names are ignored. Anyone else gets "You are not on the approver list. Nothing was changed." and the attempt is logged as `denied`.
2. **One approval, one item, one version.** `approve 3` approves the version shown on item #3's latest card. `approve all`, `approve 1 and 2` and "approve the roofing one" approve nothing.
3. **Only explicit commands approve.** "yes", "looks good", "send it", a thumbs-up: none of these approve. The bot answers with how to approve.
4. **Silence is not approval.** Nothing times out into approved. An item can wait forever.
5. **An edit is a new version.** `edit 3: <text>` stores v2 as written by the human, runs the Reviewer on it, and posts a new card. v2 needs its own approval. `approve 3 v1` after that is refused as stale.
6. **The human's text is never rewritten.** A human-written version that fails review is shown as BLOCKED; the Drafter does not "fix" it. The human edits again or rejects.
7. **Blocked versions cannot be approved.** If the Reviewer found a blocking issue (an invented number, a banned phrase, a missing sign-off), approval is refused until the text is fixed by an edit. See "decisions" below.
8. **Approving twice is a no-op.** Approving a rejected item is refused. Rejected and sent are final.
9. **Voice approvals must name the version.** "Approve three version two" works; "approve three" is refused. If speech-to-text mishears the number, the version check fails and nothing is approved.
10. **What was approved is what is sent.** Approval stores the SHA-256 of the version text. `Delivery` recomputes it before sending and refuses on any mismatch.
11. **Sending is off until you turn it on.** With `SEND_ENABLED=false` an approved item is recorded as a dry run (`mode: dry_run`) and marked sent; it will not be delivered later if sending is turned on.
12. **Rate limits.** `MAX_COMMANDS_PER_MINUTE` per user, `MAX_SENDS_PER_HOUR` overall. A rate-limited send stays approved and is retried on the next tick.

## Commands

| Command | Effect |
|---|---|
| `approve N` | Approve the current version of item N (must be awaiting approval and pass review) |
| `approve N vK` / `approve N version K` | Same, but only if K is still the current version |
| `reject N [reason]` | Reject; the reason becomes a lesson |
| `edit N: <text>` | New version written by you; reviewed, then a new card |
| `edit N vK: <text>` | Same, refused if K is no longer current |
| `lesson: <text>` | Add a lesson; "never say X" also adds a banned phrase |
| `show N`, `list`, `help` | Read-only |
| `say queue` (Discord) | Read the queue aloud (Piper) or as text |

## What the audit log records

Every transition (`frm`, `to`, `actor`, `version`), every `denied`, `rate_limited` and `stale_approval_refused`, every lesson, and every send with its mode and receipt. Approval entries carry the content hash. `haa verify-audit` checks the hash chain.

## Known gaps and decisions

- **Blocked means blocked.** A person cannot override a Reviewer block with "approve anyway"; they have to edit. This is deliberate (an override is how invented facts get out), but it is a policy choice, not a law of nature.
- **`approve N` without a version** approves whatever is current. With one approver that is the version they just saw. With several approvers, one person's edit could land between another's reading and approving; requiring `vK` for everyone closes that and is a one-line change in the gate.
- **No expiry.** Old items wait indefinitely. A real deployment may want items to expire to `rejected` after some days (expiry would only ever reject, never approve).

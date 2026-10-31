# nodra-nodes-outlook

Node package for the nodra-chat Works editor (contract: docs/nodes.md, "Node contract").

- **Start: Outlook mail received** (`nodes/outlook-receive.node.json`): a trigger. Starts a run per NEW mail that matches regexes on sender, subject, raw headers and content (all optional, all must match). Data: `from`, `from_name`, `subject`, `to`, `cc`, `body`, `received`, `attachments` (saved paths, optional), `message_id`. Polled, only mail that arrives while the work is On.
- **Send email (Outlook)** (`nodes/outlook-send.node.json`): sends, saves as draft or opens the window of a mail, with classic Outlook (COM through pywin32).

Windows only: `nodra install nodra-nodes-outlook` refuses other systems, and creates `~/.nodra/venvs/nodra-nodes-outlook` with `pywin32`.
nodra-chat runs the node with that python, so nothing is installed into the UI's own environment. Outlook must be installed and signed in (the "new Outlook" has no COM).

## Inputs (standard mail keys)

Every field may be left empty when the node before provides the same key in its `data`:
`to`, `cc`, `bcc`, `subject`, `body`, `attachments` (a list or one path per line). So a Loop over `[{"to": "a@x.com", "subject": "Hi", "body": "..."}, ...]`
sends one mail per object with no further setup. A blank `body` uses the text coming in.

## Output

`output` = `Sent: <subject> to <recipient>`; `data` = `{to, subject, attachments, action}`.

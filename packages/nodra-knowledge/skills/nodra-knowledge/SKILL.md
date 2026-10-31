---
name: nodra-knowledge
description: Use when the user mentions their notes, knowledge, handbook, runbook or "soul", asks to remember or write something down for later, or wants to look something up in their saved notes on Nodra.
---

# Nodra knowledge notes

Notes are plain markdown files on this machine: `~/.nodra/knowledge/<note>.md` (`$NODRA_HOME/knowledge` when `NODRA_HOME` is set). `soul` is the user's persona note, loaded first by Nodra bots and chats. Nothing is synced or shared anywhere; copy a file by hand if the user wants to give a note to someone.

Find the CLI first: `nodra version` (if not found, try `~/.nodra/bin/nodra`).

## Read before you answer

1. `nodra knowledge list` shows the notes.
2. `nodra knowledge get NOTE` prints one note. `nodra knowledge path` prints the folder, so you can also read the files directly.
3. Rely on a note over guessing a convention; name it when you do ("per handbook ..."). If a note and the code disagree, say so; do not silently pick one.

## Write

- One topic per note, lowercase name (`a-z 0-9 . _ -`, max 64), a `# Title` line first, short sections, facts and decisions rather than chat logs.
- Edit the file under `~/.nodra/knowledge/` directly, or `nodra knowledge edit NOTE` (opens `$EDITOR`).
- Append to an existing note instead of creating a near-duplicate; `nodra knowledge list` first.
- Never put secrets, tokens or personal data in a note: bots and chats read the notes and include them in prompts.
- Ask before changing `soul`, since it shapes every bot's persona.

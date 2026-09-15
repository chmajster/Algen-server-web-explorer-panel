# Text editor: draft preservation and editing tools

- Keep edits made during an in-flight save marked as unsaved; subsequent saves use the returned disk version. Prevent duplicate submissions and closing or reloading while a write is in flight.
- Preserve drafts, selection and undo history when language or file permissions change. Abort obsolete reads and isolate editor sessions by file path.
- Preserve UTF-8 BOM and LF, CRLF or CR line endings. Offer an explicit line-ending selector; files with mixed endings require choosing a format before editing. Enforce the 1 MiB limit on serialized UTF-8 bytes.
- Add visible find/replace, go-to-line, wrapping, reload and download-copy tools, plus cursor position and Polish/English labels. Download copies include the current unsaved draft. Reload requires confirmation before discarding changes, including after a disk-version conflict.
- Indent and unindent multiline selections with Tab and Shift+Tab. Escape closes an editor search panel without closing its window; Escape followed by Tab moves focus out of the editor.
- Restore interaction with phone-width file lists while the directory tree is displayed above them; the old overlay rule incorrectly disabled pointer events on the visible list.
- Cover asynchronous saves, stale reads, locale and permission changes, newline formats, byte limits, conflicts and keyboard controls with regressions and desktop/mobile browser tests.

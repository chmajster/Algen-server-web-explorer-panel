# Repository release instructions

* Bump the patch version only after **at least 3 meaningful changes** since the previous bump. Bug fixes, features, behavior/UI changes, refactors, and compatibility improvements count; trivial formatting/comments/typos do not.
* On version bump, add a concise changelog covering all accumulated changes. Never bump without documenting them.
* Use the repository's version-bump tooling when available; otherwise update all canonical version sources manually and verify consistency.
* Run relevant tests/checks after changes and release updates.
* Commit each completed change separately with only related files and a concise message. Never include unrelated user changes.
* After the 3-change threshold is reached, bump version, update changelog, verify, commit release metadata, then reset the change count.

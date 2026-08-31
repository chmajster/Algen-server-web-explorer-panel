### Changed

- Refactored application composition, module lifecycle management, routing, background task ownership, and command execution boundaries.
- Added manifest-driven module startup, shutdown, and health hooks plus centralized read-only and privileged command runners.
- Preserved newer authentication initialization, Proxmox Advanced Manager capabilities, and desktop module shortcuts while rebasing the architecture refactor onto current `main`.

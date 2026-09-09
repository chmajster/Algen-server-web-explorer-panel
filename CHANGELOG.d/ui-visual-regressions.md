# UI visual regression fixes

- Fixed compact-phone taskbar collisions by removing low-priority transfer/background-action indicators below 360 px while preserving Start, running-app, notification, session and clock access.
- Fixed dark-mode Network Management footer buttons that inherited the light DSM gradient.
- Fixed the window close-button hover state so the close icon remains white and readable on the danger background.
- Improved muted-text contrast and selected-navigation readability in both light and dark themes.
- Made primary action fills follow the selected accent color instead of using a hard-coded blue gradient, while darkening the fill enough to retain readable white text.
- Moved the Offline Repository job drawer and connection-status banner onto the shared WebNAS layer scale so taskbar and Start-menu chrome cannot appear above modal/system-critical UI.
- Prevented the connection-status banner from covering desktop window title bars and compacted secondary connection metrics on narrow screens.
- Restored touch-sized controls on phones, including Start-launcher pin/desktop shortcut actions.
- Styled the bootstrap Retry action as a normal primary button and synchronized the browser `theme-color` metadata with the active light/dark desktop theme.
- Fixed the CI Playwright invocation so configured HTML reporting is no longer overridden and successful CI runs retain screenshots for visual inspection.
- Added targeted Vitest and Playwright regression coverage for the corrected CSS cascade, 320 px taskbar geometry, close-button hover contrast and browser theme-color synchronization.

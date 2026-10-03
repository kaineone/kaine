## ADDED Requirements

### Requirement: Detail pages scroll vertically and keep each board whole
The diagnostics and evaluation pages SHALL lay their boards out so that a board's title stays with its cards and every board is reachable by scrolling down: the page takes its content's height and the main area scrolls vertically. They SHALL never place boards in columns beyond the visible width. The console keeps its fixed, non-scrolling screen. Key/value lists SHALL give their labels at most half the row, so values stay readable. The right sidebar SHALL not be rendered on pages that do not fill it.

#### Scenario: A tall board stays whole on the diagnostics page
- **WHEN** the health board is taller than the viewport on the diagnostics page
- **THEN** its title is directly above its cards, and the boards after it are reachable by scrolling down, none positioned past the right edge of the page

#### Scenario: No empty sidebar strip
- **WHEN** a page renders nothing into the right sidebar
- **THEN** no right sidebar element is rendered

### Requirement: The EventSource wrapper installs in browsers
The Nexus auth script SHALL replace `window.EventSource` with its wrapper without error when the browser's `EventSource` defines `CONNECTING`, `OPEN` and `CLOSED` as read-only, and the wrapper SHALL expose the same constant values.

#### Scenario: Read-only constants
- **WHEN** `nexus_auth.js` loads in a page whose `EventSource` constants are non-writable
- **THEN** no error is thrown, `window.EventSource` is the wrapper, and `window.EventSource.OPEN` equals the original value

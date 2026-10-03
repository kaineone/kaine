# Nexus detail pages lay out as a readable, vertically scrolling column flow

## Why
On the diagnostics page the boards are laid out as CSS multi-column masonry inside `.page`. `.page` is a flex child of `main` with `min-height: 0`, so its height is the viewport's. A multi-column box with a fixed height does not grow downward when its content is taller: it adds columns sideways. `.page` hides horizontal overflow, so the extra columns, and every board in them, are invisible. While each board fitted the viewport this went unnoticed. The health board now always shows each service's detail, so it is about a viewport tall. Its title stays in the first column while its cards fall into the second, and the cycle, perception and research boards are pushed into columns past the right edge. The operator sees a header bar with no content under it and a page that cannot be scrolled to the rest.

Two more defects show up on the same page:
- `dl.kv` key/value lists size the label column to its longest label (`auto`), so in a narrow panel the values get a sliver and wrap one character per line.
- The right sidebar is meant to collapse when a page leaves it empty (`.rail--right:empty`), but the template leaves whitespace inside it. `:empty` does not match whitespace, so a blank 336px strip remains on every page except the console.

An older bug sits on every page. `nexus_auth.js` subclasses `EventSource` and then copies `CONNECTING`/`OPEN`/`CLOSED` onto the subclass. Browsers define those as read-only, and the subclass already inherits them, so in strict mode the copy throws. `window.EventSource` is therefore never replaced, and the wrapper's reconnect and sign-in probe never runs. The test harness defines the constants as writable, so its tests never saw the throw.

Research impact: none. Nexus is an observation surface; the study is unaffected.

## What changes
- Detail pages (every `.page` except the console) take their natural height, and `main` scrolls vertically. The console keeps its fixed, non-scrolling screen.
- `dl.kv` labels take at most half the row (`fit-content(50%)`) and wrap; values get the rest.
- `_base.html` renders the right sidebar only when the page fills it.
- `nexus_auth.js` drops the constant-copying loop. The harness's fake `EventSource` gets read-only constants, as in browsers, and still checks that the wrapper exposes them.

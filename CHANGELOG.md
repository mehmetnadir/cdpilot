# Changelog

All notable changes to cdpilot will be documented in this file.

## [0.2.0] - 2026-04-05

### Added
- **Accessibility tree snapshot** (`a11y-snapshot`) — Structured a11y data with @ref references for AI agents
- **Click by reference** (`click-ref @N`) — Click elements using a11y snapshot references
- **Annotated screenshots** (`shot-annotated`) — Screenshots with @N badge overlays on interactive elements
- **Auto-wait** — Commands automatically wait up to 5s for elements using MutationObserver
- **Batch commands** (`batch`) — Pipe JSON arrays via stdin for multi-step automation
- **Vision fallback** (`describe`) — Combined a11y snapshot + screenshot + text content in one call
- **Visual feedback system** — Persistent green glow overlay, cursor visualization, click ripples, keystroke display
- **AI control warning** — Red toast appears when user hovers during automation: "Browser is controlled by AI"
- **Multi-project isolation** — Each project directory gets its own browser port and profile automatically
- **Project management commands** — `projects`, `project-stop`, `stop-all`
- **MCP `browser_describe` tool** — Vision fallback accessible via MCP for remote AI agents

### Fixed
- Glow overlay now persists across page navigations (re-injected after navigation)
- Multi-project `CDPILOT_PROJECT_ID` env correctly passed from Node.js to Python

### Changed
- Auto-wait is now the default behavior for `click` and `fill` commands
- Persistent script cleanup deferred to 10s JS timeout instead of immediate removal

## [0.1.2] - 2026-03-20

### Added
- Initial release with 40+ CLI commands
- MCP server for Claude Code integration
- DevExtension system (native JS injection)
- Cross-platform browser detection (Brave > Chrome > Chromium)

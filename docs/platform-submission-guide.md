# Platform Submission Guide for cdpilot

> Step-by-step instructions for submitting cdpilot to tool aggregator sites.

---

## 1. AlternativeTo.net

### Steps:
1. Go to https://alternativeto.net/
2. Click "Add Application" (top-right, requires account)
3. Fill in:
   - **Name:** cdpilot
   - **Website:** https://github.com/mehmetnadir/cdpilot
   - **Description:** Zero-dependency browser automation CLI. 50KB, 40+ commands, built-in MCP server for AI agents. Uses your existing browser via Chrome DevTools Protocol. No Playwright, no Puppeteer, no Selenium.
   - **License:** MIT / Open Source
   - **Platforms:** macOS, Linux, Windows
   - **Category:** Development Tools > Browser Automation
   - **Tags:** browser-automation, cli, cdp, zero-dependency, ai-agent, mcp, web-scraping, headless-browser
4. After creation, go to the cdpilot page and add "Alternative to":
   - Playwright
   - Puppeteer
   - Selenium
   - Cypress (partial alternative)
5. Write a review highlighting:
   - 50KB vs 200-400MB install size
   - Zero dependencies
   - CLI-first (vs library approach)
   - Built-in AI agent support (MCP)

---

## 2. StackShare.io

### Steps:
1. Go to https://stackshare.io/
2. Sign in and click "+ Add a Tool"
3. Fill in:
   - **Name:** cdpilot
   - **Website:** https://github.com/mehmetnadir/cdpilot
   - **Category:** Build, Test, Deploy > Browser Testing
   - **Description:** Zero-dependency browser automation CLI with 40+ commands and built-in MCP server. Uses existing Brave/Chrome browser via CDP. ~50KB total, no Playwright/Puppeteer needed.
   - **GitHub URL:** https://github.com/mehmetnadir/cdpilot
   - **npm URL:** https://www.npmjs.com/package/cdpilot
4. After creation, add to your personal stack and any relevant "Stack Decisions"

---

## 3. LibHunt / awesome-nodejs

### LibHunt (dev-libs.com)
1. Go to https://nodejs.libhunt.com/
2. Search for "cdpilot" -- if not indexed yet, submit via:
3. https://nodejs.libhunt.com/project/add
4. Enter GitHub URL: https://github.com/mehmetnadir/cdpilot
5. It should auto-populate from GitHub metadata

### awesome-nodejs (GitHub)
1. Go to https://github.com/sindresorhus/awesome-nodejs
2. The list is curated -- open a PR to add cdpilot under "Testing" or "Command-line utilities":
   ```markdown
   - [cdpilot](https://github.com/mehmetnadir/cdpilot) - Zero-dependency browser automation CLI with 40+ commands and built-in MCP server.
   ```
3. Follow their contribution guidelines (minimum star count may apply)

### awesome-mcp-servers (GitHub)
1. Go to https://github.com/punkpeye/awesome-mcp-servers
2. Open a PR to add cdpilot under "Browser Automation" or "Web" section:
   ```markdown
   - [cdpilot](https://github.com/mehmetnadir/cdpilot) - Zero-dependency browser automation with 40+ CLI commands. Uses existing browser via CDP. ~50KB.
   ```

### awesome-chrome-devtools (GitHub)
1. Go to https://github.com/nicedoc/awesome-chrome-devtools
2. Open a PR to add under "Automation" section:
   ```markdown
   - [cdpilot](https://github.com/mehmetnadir/cdpilot) - Zero-dependency CLI for browser automation via CDP. 40+ commands, built-in MCP server.
   ```

---

## 4. Product Hunt

### Preparation:
1. Create a Product Hunt account if you don't have one
2. Go to https://www.producthunt.com/posts/new
3. Fill in:
   - **Name:** cdpilot
   - **Tagline:** Zero-dependency browser automation CLI. 50KB, 40+ commands, AI-ready.
   - **Website:** https://github.com/mehmetnadir/cdpilot
   - **Description:**
     cdpilot is a browser automation CLI that replaces Playwright and Puppeteer for common tasks. At just 50KB with zero dependencies, it connects to your existing browser via Chrome DevTools Protocol.

     Key features:
     - 40+ CLI commands (navigate, click, type, screenshot, PDF, console, network...)
     - Built-in MCP server for AI agents (Claude Code, GPT, etc.)
     - Visual feedback (green glow, cursor vis, click ripples)
     - Multi-project browser isolation
     - Device emulation, geolocation, request interception
     - Accessibility tree snapshots for AI agents

   - **Topics:** Developer Tools, Open Source, Artificial Intelligence, Productivity
   - **Makers:** Add yourself
   - **Thumbnail:** Use the demo GIF or a clean screenshot

### Tips:
- Launch on a Tuesday or Wednesday (highest traffic)
- Share with your network in the first hour
- Respond to every comment

---

## 5. DevHunt

1. Go to https://devhunt.org/
2. Submit your tool (GitHub-based, easier than Product Hunt)
3. Same description and metadata as Product Hunt

---

## 6. Uneed.best

1. Go to https://www.uneed.best/submit-a-tool
2. Submit cdpilot with:
   - Category: Developer Tools
   - Pricing: Free / Open Source

---

## 7. MCP-specific Directories

### Smithery.ai
1. Go to https://smithery.ai/
2. Submit cdpilot as an MCP server
3. Include the MCP config snippet:
   ```json
   {
     "mcpServers": {
       "cdpilot": {
         "command": "npx",
         "args": ["cdpilot", "mcp"]
       }
     }
   }
   ```

### glama.ai/mcp
1. Go to https://glama.ai/mcp/servers
2. Submit cdpilot MCP server

### mcp.so
1. Go to https://mcp.so
2. Submit cdpilot as an MCP server listing

---

## Tracking

| Platform | Status | URL | Date |
|----------|--------|-----|------|
| AlternativeTo | Pending | | |
| StackShare | Pending | | |
| LibHunt | Pending | | |
| awesome-nodejs PR | Pending | | |
| awesome-mcp-servers PR | Pending | | |
| awesome-chrome-devtools PR | Pending | | |
| Product Hunt | Pending | | |
| DevHunt | Pending | | |
| Uneed | Pending | | |
| Smithery.ai | Pending | | |
| glama.ai/mcp | Pending | | |
| mcp.so | Pending | | |

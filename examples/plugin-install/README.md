# plugin-install

This example details how to register the cdpilot plugin marketplace, install the plugin, and build the `.mcpb` bundle using `npm run build:mcpb`.

## Commands

```text
/plugin marketplace add mehmetnadir/cdpilot
/plugin install cdpilot@cdpilot
npm run build:mcpb
```

## Captured Output

```text
$ npm run build:mcpb

> cdpilot@0.9.3 build:mcpb
> bash scripts/build-mcpb.sh

Validating manifest.json...
Manifest schema validation passes!
Packing ~/01dev/cdpilot/.claude/worktrees/w-examples -> ~/01dev/cdpilot/.claude/worktrees/w-examples/cdpilot.mcpb
Validating manifest...
Manifest schema validation passes!

📦  cdpilot@0.9.3
Archive Details
name: cdpilot
version: 0.9.3
filename: cdpilot-0.9.3.mcpb
package size: 381.9kB
unpacked size: 1.0MB
shasum: 8468f6fa99fd427c41b90ed8be12061e28227f5f

Output: ~/01dev/cdpilot/.claude/worktrees/w-examples/cdpilot.mcpb
Verifying bundle info...
File: cdpilot.mcpb
Size: 381.94 KB

WARNING: Not signed
Built ~/01dev/cdpilot/.claude/worktrees/w-examples/cdpilot.mcpb
```

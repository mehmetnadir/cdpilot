# Contributing to cdpilot

Thanks for your interest in contributing!

## Development Setup

```bash
git clone https://github.com/mehmetnadir/cdpilot.git
cd cdpilot
npm install
```

## Running Locally

```bash
# Run directly
node bin/cdpilot.js <command>

# Or link globally
npm link
cdpilot <command>
```

## Testing

```bash
npm test
```

## Pull Requests

1. Fork the repo and create your branch from `main`
2. Add tests for any new functionality
3. Ensure the test suite passes
4. Update README.md if you changed commands or behavior
5. Submit a PR with a clear description

## Code Style

- Python: PEP 8, type hints where possible
- JavaScript: No semicolons preference, ES6+
- Keep it simple — no unnecessary abstractions

## Reporting Issues

- Include your OS, Node.js version, Python version, and browser
- Include the exact command that failed
- Include the error output

## License

By contributing, you agree that your contributions will be licensed under the MIT License.

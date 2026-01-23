# Claude Code Configuration

This directory contains Claude Code settings for the project.

## Security Settings

### 🚨 ALL DEPLOYMENTS BLOCKED 🚨

**CRITICAL: Claude Code and all AI tools are blocked from deploying to Railway.**

The `settings.json` file contains restrictions that prevent Claude Code and any MCP-based AI tools from deploying to ANY environment (production or non-production). All deployments must be done manually.

**Blocked Actions (ALL ENVIRONMENTS):**
- ❌ `railway up` - All deployment commands
- ❌ `make deploy` - All deployment commands (any environment)
- ❌ `railway domain` - Domain generation
- ❌ `railway link` / `railway environment link` - Environment linking
- ❌ All MCP deployment tools (deploy, deploy-template, create-environment)
- ❌ All MCP modification tools (link-service, link-environment, set-variables, generate-domain, create-project-and-link)

**Why This Policy?**
ALL deployments should be:
1. Intentional and reviewed by a human
2. Performed manually by authorized personnel
3. NEVER done automatically by AI assistants
4. Traceable and auditable

### ✅ Allowed Actions (Read-Only)

AI tools CAN perform read-only operations:

**Railway CLI Commands:**
- `railway logs` - View deployment logs
- `railway status` - Check deployment status
- `railway variables` - List environment variables
- `railway whoami` - Check authentication

**Makefile Commands:**
- `make logs` - View logs
- `make status` - Check status
- `make variables` - List variables

**Railway MCP Server Tools (Read-Only):**
- `check-railway-status` - Check CLI status
- `list-services` - List services
- `list-variables` - View variables
- `get-logs` - Fetch logs
- `list-projects` - List projects
- `list-deployments` - List deployments

### Files

- `settings.json` - Project-wide settings (committed to git, shared with team)

## For Developers

### Deploying (Manual Only)

**ALL deployments MUST be done manually, outside of Claude Code:**
```bash
make deploy              # Deploy to non-prod (manual only)
make deploy ENV=production  # Deploy to production (manual only)
```

### Using Claude Code for Development

Claude Code can help you with:
- ✅ Code development and refactoring
- ✅ Writing tests
- ✅ Debugging issues
- ✅ Viewing logs and status (read-only)
- ✅ Documentation
- ❌ **NO deployments** - all deployments must be done manually
- ❌ **NO environment modifications** - no linking, variable changes, or domain generation

## Questions?

Contact the team lead if you have questions about these security measures.

# Claude Code Configuration

This directory contains Claude Code settings for the project.

## Security Settings

### Production Deployment Protection

The `settings.json` file contains restrictions that prevent Claude Code from deploying to production. These settings are enforced for all team members using Claude Code.

**Blocked Actions:**
- Linking to production environment
- Deploying to production via `make deploy ENV=production`
- Any Railway commands that target production
- Any Railway MCP server actions targeting production

**Why?**
Production deployments should be:
1. Intentional and reviewed
2. Performed by authorized personnel
3. Never done automatically by AI assistants

### Enabled Features

The configuration pre-approves the following actions for all developers:

**Railway CLI Commands:**
- `railway logs`, `status`, `env`, `list`, `variables`, `whoami`
- `railway link`, `up`, `domain`, `service`, `run`

**Makefile Commands:**
- `make deploy` (non-prod only)
- `make logs`, `status`, `domain`

**Railway MCP Server Tools:**
- Check Railway status
- List services, variables, projects, deployments
- Deploy to non-production environments
- Link services
- Set variables (non-production)
- Get logs
- Generate domains
- Deploy from templates

### Files

- `settings.json` - Project-wide settings (committed to git, shared with team)
- `settings.local.json` - Personal settings (gitignored, not shared)

## For Developers

### Deploying to Non-Production
Claude Code can help you deploy to non-production environments:
```bash
make deploy              # Deploys to non-prod by default
make deploy ENV=non-prod # Explicitly deploy to non-prod
```

### Deploying to Production (Manual Only)
If you need to deploy to production manually:
1. Ensure you have proper authorization
2. Use the Makefile: `make deploy ENV=production`
3. Type "YES" to confirm when prompted
4. Claude Code will not be able to perform this action

### Railway MCP Server
The Railway MCP server is configured for this project, allowing Claude to:
- View Railway project information
- Deploy to non-production environments
- Manage environment variables
- View logs and deployment status

All production-related MCP actions are blocked.

## Questions?

Contact the team lead if you have questions about these security measures.

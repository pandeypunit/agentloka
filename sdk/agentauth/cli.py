"""AgentAuth CLI — command-line interface for agent management."""

import json
import sys

import click

from agentauth.client import AgentAuth


@click.group()
@click.option("--registry", default="http://localhost:8000", help="Registry URL")
@click.pass_context
def cli(ctx, registry):
    """AgentAuth — the identity layer for AI agents."""
    ctx.ensure_object(dict)
    ctx.obj["auth"] = AgentAuth(registry_url=registry)


@cli.command()
@click.argument("agent_name")
@click.option("--description", "-d", default=None, help="Agent description")
@click.pass_context
def register(ctx, agent_name, description):
    """Register a new agent and save credentials locally."""
    auth: AgentAuth = ctx.obj["auth"]
    try:
        result = auth.register(agent_name, description=description)
        click.echo(f"Agent '{agent_name}' registered successfully.")
        click.echo(f"  Registry Secret Key: {result['registry_secret_key']}")
        click.echo(f"  Proof Token: {result['platform_proof_token']}")
        click.echo("\n  Save your registry_secret_key — it is shown only once. NEVER send it to platforms.")
    except Exception as e:
        click.echo(f"Registration failed: {e}", err=True)
        sys.exit(1)


@cli.command("list")
@click.pass_context
def list_agents(ctx):
    """List all locally registered agents."""
    auth: AgentAuth = ctx.obj["auth"]
    agents = auth.list_agents()
    if not agents:
        click.echo("No agents registered locally.")
        return
    for agent in agents:
        click.echo(f"  {agent['name']}  (key: {agent['registry_secret_key'][:20]}...)")


@cli.command()
@click.argument("agent_name")
@click.pass_context
def me(ctx, agent_name):
    """Fetch your agent's profile from the registry."""
    auth: AgentAuth = ctx.obj["auth"]
    try:
        profile = auth.get_me(agent_name)
        click.echo(json.dumps(profile, indent=2, default=str))
    except FileNotFoundError as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)
    except Exception as e:
        click.echo(f"Failed: {e}", err=True)
        sys.exit(1)


@cli.command()
@click.argument("agent_name")
@click.pass_context
def revoke(ctx, agent_name):
    """Revoke an agent from the registry and delete local credentials."""
    auth: AgentAuth = ctx.obj["auth"]
    try:
        revoked = auth.revoke(agent_name)
        if revoked:
            click.echo(f"Agent '{agent_name}' revoked.")
        else:
            click.echo(f"Failed to revoke '{agent_name}' — invalid key or not found.")
    except FileNotFoundError as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)
    except Exception as e:
        click.echo(f"Revocation failed: {e}", err=True)
        sys.exit(1)


# --- Platform commands ---


@cli.group()
def platform():
    """Platform registration and management."""
    pass


@platform.command("register")
@click.argument("platform_name")
@click.option("--domain", "-d", required=True, help="Platform domain (e.g. myplatform.example.com)")
@click.option("--description", "-D", default=None, help="Short description (max 140 chars)")
@click.option("--email", "-e", default=None, help="Optional email for verification")
@click.pass_context
def platform_register(ctx, platform_name, domain, description, email):
    """Register a new platform and save credentials locally."""
    auth: AgentAuth = ctx.obj["auth"]
    try:
        result = auth.register_platform(platform_name, domain=domain, description=description, email=email)
        click.echo(f"Platform '{platform_name}' registered successfully.")
        click.echo(f"  Platform Secret Key: {result['platform_secret_key']}")
        click.echo(f"  Domain: {result['domain']}")
        click.echo("\n  Save your platform_secret_key — it is shown only once.")
    except Exception as e:
        click.echo(f"Registration failed: {e}", err=True)
        sys.exit(1)


@platform.command("info")
@click.argument("platform_name")
@click.pass_context
def platform_info(ctx, platform_name):
    """Look up a platform's public profile."""
    auth: AgentAuth = ctx.obj["auth"]
    try:
        profile = auth.get_platform(platform_name)
        click.echo(json.dumps(profile, indent=2, default=str))
    except Exception as e:
        click.echo(f"Failed: {e}", err=True)
        sys.exit(1)


@platform.command("revoke")
@click.argument("platform_name")
@click.pass_context
def platform_revoke(ctx, platform_name):
    """Revoke a platform from the registry and delete local credentials."""
    auth: AgentAuth = ctx.obj["auth"]
    try:
        revoked = auth.revoke_platform(platform_name)
        if revoked:
            click.echo(f"Platform '{platform_name}' revoked.")
        else:
            click.echo(f"Failed to revoke '{platform_name}' — invalid key or not found.")
    except FileNotFoundError as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)
    except Exception as e:
        click.echo(f"Revocation failed: {e}", err=True)
        sys.exit(1)


@platform.command("report")
@click.argument("agent_name")
@click.option("--key", "-k", required=True, help="Platform secret key (platauth_...)")
@click.pass_context
def platform_report(ctx, agent_name, key):
    """Report a misbehaving agent."""
    auth: AgentAuth = ctx.obj["auth"]
    try:
        reported = auth.report_agent(key, agent_name)
        if reported:
            click.echo(f"Agent '{agent_name}' reported.")
        else:
            click.echo(f"Agent '{agent_name}' is already reported by this platform.")
    except Exception as e:
        click.echo(f"Report failed: {e}", err=True)
        sys.exit(1)


@platform.command("retract")
@click.argument("agent_name")
@click.option("--key", "-k", required=True, help="Platform secret key (platauth_...)")
@click.pass_context
def platform_retract(ctx, agent_name, key):
    """Retract a report against an agent."""
    auth: AgentAuth = ctx.obj["auth"]
    try:
        retracted = auth.retract_report(key, agent_name)
        if retracted:
            click.echo(f"Report against '{agent_name}' retracted.")
        else:
            click.echo(f"No report found against '{agent_name}' from this platform.")
    except Exception as e:
        click.echo(f"Retraction failed: {e}", err=True)
        sys.exit(1)


@platform.command("reports")
@click.argument("agent_name")
@click.pass_context
def platform_reports(ctx, agent_name):
    """View reports against an agent (public, no auth needed)."""
    auth: AgentAuth = ctx.obj["auth"]
    try:
        result = auth.get_agent_reports(agent_name)
        click.echo(json.dumps(result, indent=2))
    except Exception as e:
        click.echo(f"Failed: {e}", err=True)
        sys.exit(1)


def main():
    cli()


if __name__ == "__main__":
    main()

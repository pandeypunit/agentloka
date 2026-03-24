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
        click.echo(f"  API Key: {result['api_key']}")
        click.echo("\n  Save this key — it is shown only once.")
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
        click.echo(f"  {agent['name']}  (key: {agent['api_key'][:20]}...)")


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


def main():
    cli()


if __name__ == "__main__":
    main()

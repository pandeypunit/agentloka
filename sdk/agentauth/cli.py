"""AgentAuth CLI — command-line interface for agent management."""

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
@click.option("--label", default="default", help="Label for this master key")
@click.pass_context
def init(ctx, label):
    """Generate master keypair and register with the registry."""
    auth: AgentAuth = ctx.obj["auth"]
    try:
        result = auth.init(label=label)
        click.echo(f"Master key registered successfully.")
        click.echo(f"  Key ID:     {result['key_id']}")
        click.echo(f"  Public Key: {result['public_key']}")
        click.echo(f"  Label:      {result['label']}")
    except RuntimeError as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)
    except Exception as e:
        click.echo(f"Failed to register with registry: {e}", err=True)
        sys.exit(1)


@cli.command()
@click.argument("agent_name")
@click.option("--description", "-d", default=None, help="Agent description")
@click.pass_context
def register(ctx, agent_name, description):
    """Register a new agent."""
    auth: AgentAuth = ctx.obj["auth"]
    try:
        creds = auth.register(agent_name, description=description)
        click.echo(f"Agent '{agent_name}' registered successfully.")
        click.echo(f"  Public Key: {creds.agent_public_key}")
        click.echo(f"  Master Key: {creds.master_public_key}")
    except RuntimeError as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)
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
        click.echo("No agents registered.")
        return
    for agent in agents:
        click.echo(f"  {agent.agent_name}  (key: {agent.agent_public_key[:16]}...)")


@cli.command()
@click.argument("agent_name")
@click.pass_context
def revoke(ctx, agent_name):
    """Revoke an agent."""
    auth: AgentAuth = ctx.obj["auth"]
    try:
        revoked = auth.revoke(agent_name)
        if revoked:
            click.echo(f"Agent '{agent_name}' revoked.")
        else:
            click.echo(f"Agent '{agent_name}' was already removed from registry. Local credentials cleaned up.")
    except Exception as e:
        click.echo(f"Revocation failed: {e}", err=True)
        sys.exit(1)


@cli.command()
@click.argument("agent_name")
@click.pass_context
def auth_token(ctx, agent_name):
    """Get authentication payload for an agent."""
    auth: AgentAuth = ctx.obj["auth"]
    try:
        token = auth.authenticate(agent_name)
        import json
        click.echo(json.dumps(token, indent=2))
    except FileNotFoundError as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)


def main():
    cli()


if __name__ == "__main__":
    main()

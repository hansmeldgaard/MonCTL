"""Collector daemon CLI entry point."""

from __future__ import annotations

import asyncio
import sys

import click
import structlog

from monctl_collector.config import collector_settings

logger = structlog.get_logger()


@click.group()
def cli():
    """MonCTL Collector - Distributed monitoring agent."""
    pass


@cli.command()
@click.option("--central-url", default=None, help="Central server URL")
@click.option("--token", default=None, help="Registration token")
@click.option("--cluster-id", default=None, help="Cluster to join")
@click.option("--peer-address", default=None, help="Address for peer communication")
@click.option("--labels", default=None, help="Labels as key=value,key=value")
def register(central_url, token, cluster_id, peer_address, labels):
    """Register this collector with the central server."""
    from monctl_collector.registration.service import register_collector

    url = central_url or collector_settings.central_url
    reg_token = token or collector_settings.registration_token

    if not reg_token:
        click.echo("Error: Registration token is required (--token or MONCTL_COLLECTOR_REGISTRATION_TOKEN)")
        sys.exit(1)

    parsed_labels = {}
    if labels:
        for pair in labels.split(","):
            k, v = pair.split("=", 1)
            parsed_labels[k.strip()] = v.strip()

    asyncio.run(register_collector(
        central_url=url,
        registration_token=reg_token,
        cluster_id=cluster_id,
        peer_address=peer_address,
        labels=parsed_labels,
    ))


@cli.command()
@click.option("--config", default=None, help="Path to config file")
def start(config):
    """Start the collector daemon."""
    from monctl_collector.daemon import CollectorDaemon

    daemon = CollectorDaemon()
    try:
        asyncio.run(daemon.start())
    except KeyboardInterrupt:
        logger.info("collector_interrupted")


@cli.command()
def status():
    """Show collector status."""
    click.echo(f"Collector ID: {collector_settings.collector_id or 'Not registered'}")
    click.echo(f"Central URL: {collector_settings.central_url}")
    click.echo(f"Cluster ID: {collector_settings.cluster_id or 'Standalone'}")


if __name__ == "__main__":
    cli()

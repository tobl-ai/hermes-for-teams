"""Hermes directory-plugin entry point."""
def register(ctx):
    from importlib import import_module
    module = f'{__package__}.hermes_for_teams.plugin' if __package__ else 'hermes_for_teams.plugin'
    return import_module(module).register(ctx)

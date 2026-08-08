import typer

app = typer.Typer()


@app.command()
def deploy(env: str, dry_run: bool = False) -> None:
    print(env, dry_run)

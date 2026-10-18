from contextlib import redirect_stderr, redirect_stdout
from io import StringIO

from scripts.dbc_skill import cli


def run_cli(args):
    stdout = StringIO()
    stderr = StringIO()
    with redirect_stdout(stdout), redirect_stderr(stderr):
        exit_code = cli.main(args)
    return exit_code, stdout.getvalue(), stderr.getvalue()

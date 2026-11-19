# Contributing

**English** · [한국어](CONTRIBUTING.ko.md)

For security issues involving automatic approval scope or permission handling, follow the [security reporting guide](SECURITY.md).

When reporting a bug, include your operating system, Python version, the agent and its version, the command you ran, and what you expected and observed. Remove tokens, personal paths, and private project information before sharing logs.

After changing the code, install the package from the repository root and check that the CLI runs.

```sh
uv tool install .
agent-auto-approve --help
```

Use a temporary home directory and project when testing `install` or `uninstall`. In your pull request, explain why you made the change and how you verified it.

## Releases

Update `version` in `setup.cfg` and merge the change into `main`. Then create and push a matching tag in the form `vMAJOR.MINOR.PATCH`. For example, use the commands below for package version `0.1.0`.

```sh
git tag -a v0.1.0 -m 'Release v0.1.0'
git push origin v0.1.0
```

Once CI passes for the tagged commit, the workflow attaches the wheel (`.whl`) and source distribution (`.tar.gz`) to a GitHub release.

To enable automatic publishing, register a Trusted Publisher on PyPI. Use `agent-auto-approve` for both the project and repository names, `jiind` for the GitHub owner, `release.yml` for the workflow, and `pypi` for the environment. Before pushing the first release tag, create the `pypi` environment in the GitHub repository and set the Actions variable `PUBLISH_TO_PYPI` to `true`. [PyPI Trusted Publishing](https://docs.pypi.org/trusted-publishers/adding-a-publisher/)

# Self-hosted runner

The `deploy-dev` and `promote` jobs run on a GitHub Actions **self-hosted runner** with the labels `self-hosted, splitsnap`. The runner must be on a machine with Docker. It uses your existing GitHub account; no other service is involved.

## One-time setup (Windows + Docker Desktop)

```powershell
# from the repo root, in PowerShell
./deploy/runner/setup-runner.ps1            # downloads actions/runner from github.com and registers it
cd $HOME\actions-runner-splitsnap; ./run.cmd # start it (keep the window open, or install as a service)
```

On Linux or macOS, follow GitHub's instructions under *Settings → Actions → Runners → New self-hosted runner* and add the label `splitsnap`.

## Safety

- Self-hosted jobs only run from `workflow_run` (CI succeeded on a **push** to `main` in this repository) and from manual `workflow_dispatch`. Pull requests, including those from forks, never reach this machine.
- Additionally, under *Settings → Actions → General → Fork pull request workflows*, keep "Require approval for all outside collaborators" turned on.

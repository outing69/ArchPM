# Security

## What runs as root

Exactly one file: `archpm/root/helper.py`, installed root-owned as
`/usr/local/lib/archpm/archpm-helper` and invoked through `pkexec`. Nothing else in
this project ever runs with elevated privileges. The GUI never sees a password;
polkit handles authentication.

## Threat model

The helper assumes its caller is **an unprivileged process in your own desktop
session** and treats every argument as hostile. It defends against:

- **Command injection.** No shell is ever started. Every external command
  (`systemctl`, `ionice`) is run as an argv list with a fixed, clean `PATH`.
- **Arbitrary actions.** Only a fixed set of subcommands exists. Signals are
  limited to an allow-list, service actions to start/stop/restart, and every
  numeric value has explicit bounds.
- **Breaking your session.** A list of protected units (dbus, logind,
  journald, udev, polkit, the display manager) cannot be stopped or restarted.
  PID 1 and below are always refused.
- **Loading attacker-controlled code.** The helper is stdlib-only, imports
  nothing from this repository, and lives in a directory a normal user cannot
  write to. `pkexec` itself refuses to run a binary that is not root-owned.

The helper does **not** defend against:

- A caller who has already authenticated. With `auth_admin_keep`, polkit
  remembers a successful authentication for roughly five minutes. During that
  window any process in your session can call the helper without a new prompt.
  If that worries you, change `auth_admin_keep` to `auth_admin` in
  `polkit/io.github.outing69.archpm.policy` and reinstall with
  `./install.sh --root`. You will then be asked for your password on every action.
- Malicious software already running as root. That is game over regardless.

## What the tests cover

`tests/test_helper.py` pins every refusal rule above so that a later change
cannot silently loosen it. Run them with:

```bash
python3 -m unittest discover tests
```

## Reporting a problem

This is a hobby project without a security team. If you find something in the
helper or the polkit policy, open a GitHub issue. If you would rather not make
it public straight away, use GitHub's private vulnerability reporting on the
repository's Security tab. Please describe the problem and how to trigger it;
there is no bounty and no guaranteed response time.

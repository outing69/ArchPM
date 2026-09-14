# Security

## What runs as root

Exactly one file: `archpm/root/helper.py`, installed root-owned as
`/usr/lib/archpm/archpm-helper` (package) or `/usr/local/lib/archpm/archpm-helper`
(install.sh) and invoked through `pkexec`. Nothing else in
this project ever runs with elevated privileges. The GUI never sees a password;
polkit handles authentication.

## Threat model

The helper assumes its caller is **an unprivileged process in your own desktop
session** and treats every argument as hostile. It defends against:

- **Command injection.** No shell is ever started. Every external command
  (`ionice`, `paccache`, `journalctl`) is run as an argv list with a fixed,
  clean `PATH`. The helper never runs `systemctl`.
- **Arbitrary actions.** Only a fixed set of subcommands exists. Signals are
  limited to an allow-list and every numeric value has explicit bounds. The
  helper does not manage services at all (see below).
- **Breaking your session.** Two rules:
  - Signals go only to processes of regular users (uid 1000 and up) that are
    not inside a protected unit's cgroup (dbus, logind, journald, udev, polkit,
    oomd, the common display managers and their sockets). Root daemons,
    polkitd, dbus, the display manager and their children cannot be signalled
    by pid at all. The check runs on a pidfd, so a pid recycled mid-call cannot
    receive the signal.
  - PID 1 and below are always refused for everything.
- **Loading attacker-controlled code.** The helper is stdlib-only, imports
  nothing from this repository, and lives in a directory a normal user cannot
  write to. `pkexec` itself refuses to run a binary that is not root-owned.

The helper does **not** defend against:

- A caller who has already authenticated. The policy sets `allow_active` to
  `auth_admin_keep`, which makes polkit remember a successful authentication
  for roughly five minutes. During that window any process in your session can
  call the helper without a new prompt. This retention is a property of that
  setting, not of the action, which is why the password prompt itself does not
  mention it. If you prefer a prompt every time, there are two routes,
  depending on how you installed the root part:
  - **Manual install (`install.sh`)**: change `auth_admin_keep` to `auth_admin`
    in `polkit/io.github.outing69.archpm.policy` and reinstall with
    `./install.sh --root`.
  - **Package**: do not edit the packaged policy. Pacman never overwrites a
    file it owns that you have edited; on an update it writes the new version
    as a `.pacnew` next to it and leaves your edit in place until you merge
    them, which is easy to forget. Instead add a rules file, which survives
    updates and touches no packaged file. As root, create
    `/etc/polkit-1/rules.d/49-archpm.rules` containing:

    ```js
    // Ask for the administrator password on every ArchPM root action
    // instead of remembering it for a few minutes.
    polkit.addRule(function(action, subject) {
        if (action.id == "io.github.outing69.archpm.helper.run") {
            return polkit.Result.AUTH_ADMIN;
        }
    });
    ```

    Rules files are read in lexical order of their name and the first one
    that returns a value decides, so this one runs before the packaged
    `50-default.rules` and takes precedence over the `auth_admin_keep`
    default in the policy. The directory is only readable by root and the
    polkitd group, so the file needs `sudo`; plain `root:root 0644` is fine.
    Polkit picks the change up immediately. Syntax checked against the
    polkit(8) manual page of polkit 127.
- Malicious software already running as root. That is game over regardless.
- Renice, affinity and ionice have no owner check and are subject to the usual
  pid-reuse race. The worst case is a wrong process getting a different
  priority, which is why these three are not gated the way signals are.
- The last line of ionice's, paccache's or journalctl's stderr is passed back
  to the caller in the JSON error. That can name paths; it cannot leak secrets.

This helper was reviewed once by an independent automated adversarial pass on
13 September 2026, which found the signal-by-pid bypass described above and two
gaps in the service subcommand that existed at the time. The bypass is fixed
and pinned by tests; the service subcommand has since been removed altogether.
It has not yet been reviewed by a second person.

## Services

The helper no longer manages services at all. ArchPM manages only the services
of your own login session, through `systemctl --user`, run as you from
`archpm/actions.py`: no `pkexec`, no password, no root. A root process running
`systemctl --user` would address root's own user manager rather than yours, so
routing them through the helper was both wrong and unnecessary. System-wide
services are never started, stopped or restarted by ArchPM.

Two things remain guarded on the client side. Only `start`, `stop` and
`restart` exist, with a unit-name check and `--` before the name so nothing
can be read as an option. And a unit your desktop session itself runs on
(plasma-plasmashell, pipewire, wireplumber, xdg-desktop-portal, including
variants such as pipewire-pulse and xdg-desktop-portal-kde) is refused for
`stop`, with a message saying what you would lose; restarting it stays allowed,
because that is how you recover it. This guard protects you from a mistake,
not from an attacker: anything running as you can run `systemctl --user` itself.

An old client that still sends `service` to the helper gets a JSON refusal and
no command is run.

## The two cleanup commands

`paccache-clean` runs `paccache -rk2` and `journal-vacuum` runs
`journalctl --vacuum-size=100M`, exactly like that, with no argument from the
caller: the subcommands accept none. They remove old package versions (the last
two of each package are kept) and archived journal files beyond 100 MB. Nothing
else on the Cleanup tab needs root; the user-level items are emptied by the GUI
inside the user's own cache folders, symlinks never followed.

## What the tests cover

`tests/test_helper.py` pins every refusal rule above so that a later change
cannot silently loosen it, including that the `service` subcommand stays gone.
`tests/test_actions.py` pins the session guard and that services never go
through `pkexec`. Run them with:

```bash
python3 -m unittest discover tests
```

## Reporting a problem

This is a hobby project without a security team. If you find something in the
helper or the polkit policy, open a GitHub issue. If you would rather not make
it public straight away, use GitHub's private vulnerability reporting on the
repository's Security tab. Please describe the problem and how to trigger it;
there is no bounty and no guaranteed response time.

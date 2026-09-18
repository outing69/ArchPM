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
  (`ionice`, `paccache`, `journalctl`, `snapper`, `timeshift`, `ufw status`,
  `firewall-cmd`) is run as an argv list with a fixed, clean `PATH`. The
  helper never runs `systemctl`. The firewall command is read-only: it
  returns the tool's own status text and takes nothing from the caller.
- **Arbitrary actions.** Only a fixed set of subcommands exists. Signals are
  limited to an allow-list and every numeric value has explicit bounds. The
  helper does not manage services at all (see below).
- **Breaking your session.** Two rules, the same for all four process
  commands (signal, nice, affinity, IO class):
  - The target must be a regular user's process, as `/etc/login.defs` defines
    a regular user: `UID_MIN` to `UID_MAX`, 1000 to 60000 on Arch and most
    distributions. System accounts below that range are refused, and so are
    `nobody` (65534) and systemd's `DynamicUser` accounts (61184 to 65519)
    above it. And it must not sit inside a protected unit's cgroup (dbus,
    logind, journald, udev, polkit, oomd, the common display managers and
    their sockets). So root daemons, polkitd, dbus, the display manager and
    their children cannot be signalled, reniced, pinned to a core or given a
    realtime IO class by pid at all.
  - Every command pins the target with a pidfd before it looks at who it is. A
    signal is delivered through that pidfd, so a pid recycled mid-call cannot
    receive it. Nice, affinity and IO class have to address a pid, so after
    the change the helper checks that the pinned process is still alive; a pid
    is only handed out again once its process has exited, so a live pidfd
    means the pid named the same process throughout. If it did exit, the
    helper reports that the change may have reached a newcomer instead of
    reporting success.
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
- The last line of ionice's, paccache's or journalctl's stderr is passed back
  to the caller in the JSON error. That can name paths; it cannot leak secrets.

This helper was reviewed once by an independent automated adversarial pass on
13 September 2026, which found the signal-by-pid bypass described above and two
gaps in the service subcommand that existed at the time. The bypass is fixed
and pinned by tests; the service subcommand has since been removed altogether.
A second outside review on 16 September 2026 found that nice, affinity and IO
class still checked only that the pid existed, so with root a user could renice
journald or the display manager, and that the system-account bound stopped at
uid 999, which treated `nobody` and `DynamicUser` accounts as regular users.
Both are fixed as described above and pinned by tests.

**The user side retries only for lack of privileges.** The window first tries
every process action as you. Before 0.2.15 the elevated backend retried any
refusal through the helper, so a refusal meant as final, ArchPM's own process
for instance, came back as a root action. Now only a refusal for lack of
privileges (another user's process, a nice value below the current one, a
realtime IO class) goes through `pkexec`; every other refusal stands.

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
(plasma-plasmashell, plasma-kwin_wayland, plasma-ksmserver, dbus-broker,
pipewire, wireplumber, xdg-desktop-portal, including variants such as
pipewire-pulse and xdg-desktop-portal-kde) is refused for `stop`, with a
message saying what you would lose; restarting it stays allowed, because that
is how you recover it. That list lives in `archpm/session.py` and is the same
one the signal guard reads by process name, so the two cannot drift apart; a
dbus-activated program's unit (`dbus-:1.2-…@0.service`) is that program, not
the bus, and may be stopped. This guard protects you from a mistake, not from
an attacker: anything running as you can run `systemctl --user` itself.

An old client that still sends `service` to the helper gets a JSON refusal and
no command is run.

## The two cleanup commands

`paccache-clean` runs `paccache -rk2` and `journal-vacuum` runs
`journalctl --vacuum-size=100M`, exactly like that, with no argument from the
caller: the subcommands accept none. They remove old package versions (the last
two of each package are kept) and archived journal files beyond 100 MB. Nothing
else on the Cleanup tab needs root; the user-level items are emptied by the GUI
inside the user's own cache folders, symlinks never followed.

## The status file and the widgets

The agent (or the window, when the agent service is not running) writes
`status.json` for the two Plasma widgets. That file is **data only**. Since
0.2.14 the widgets run nothing that comes out of it:

- **Open ArchPM** starts ArchPM by a command fixed when the widget is
  installed. `install.sh` renders the checkout's `main.py` path into the QML,
  the package renders `/usr/bin/archpm`. Nothing in the file says how to start
  anything.
- **End game** starts ArchPM the same way with `--end-game`, or hands that
  request to the running window over its instance socket, which only the same
  user can reach. The window then does exactly what its own End game button
  does: it asks, runs the signal guard in `archpm/signalguard.py` (ArchPM's
  own ancestors, your session leader, plasmashell, kwin and the sound stack
  are refused or warned about) and sends through the active backend. The
  process tree comes from the window's own sample, never from the file.

Before 0.2.14 the file carried a `launch` command line and the game's pids,
and the widget ran them through the shell. Anything that could write the file
as you, a sandboxed app with access to your home folder for instance, could run
a command inside plasmashell that way, and the guard above never saw the pids.

**Where the file goes.** `$XDG_RUNTIME_DIR/archpm/status.json`, with a symlink
from `~/.cache/archpm/status.json` because that is the path the widget can
predict. Without a runtime directory the file goes into `~/.cache/archpm`
itself. It never goes into a shared temporary directory: a directory another
user can create first is a directory another user can replace the file in, and
before 0.2.14 that was the fallback. Every write opens the directory first and
checks the open descriptor with `fstat`, not the path, so the directory cannot
be swapped between the check and the write: it must be a real directory and
not a symlink, owned by the current user, with no write bit for group or
others. The file is then written through that descriptor with `openat` and
renamed into place. If the check fails, nothing is written. The agent prints
the reason and exits with status 3, which the unit lists in
`RestartPreventExitStatus` so systemd does not restart it into the same wall;
the window shows the reason in its status bar and stops publishing for that
run. Refusing to publish and saying so beats publishing somewhere unsafe.

**An old widget with a new agent** loses both buttons: "Open ArchPM" is hidden
because the `launch` field is gone, and "End game" does nothing because the
pids are gone. Both are the safe failure. Reinstall the widgets with
`./install.sh` or the package and both come back.

## What the tests cover

`tests/test_helper.py` pins every refusal rule above so that a later change
cannot silently loosen it: the uid range with `nobody` and `DynamicUser`
refused, the protected units, the pidfd pin for all four process commands,
and that the `service` subcommand stays gone. `tests/test_actions.py` pins
that the elevated backend retries only a permission refusal through the helper.
`tests/test_actions.py` pins the session guard and that services never go
through `pkexec`. `tests/test_publisher_agent.py` pins the directory check (a
foreign owner, a world-writable directory, a symlink and a plain file are all
refused) and that the file carries no `launch` field and no pids.
`tests/test_instance_requests.py` pins that the instance socket acts on `show`
and `end-game` only. Run them with:

```bash
python3 -m unittest discover tests
```

## Reporting a problem

This is a hobby project without a security team. If you find something in the
helper or the polkit policy, open a GitHub issue. If you would rather not make
it public straight away, use GitHub's private vulnerability reporting on the
repository's Security tab. Please describe the problem and how to trigger it;
there is no bounty and no guaranteed response time.

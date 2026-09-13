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
- **Breaking your session.** Three rules, each closing a hole the previous
  one leaves open:
  - Signals go only to processes of regular users (uid 1000 and up) that are
    not inside a protected unit's cgroup. Root daemons, polkitd, dbus, the
    display manager and their children cannot be signalled by pid at all. The
    check runs on a pidfd, so a pid recycled mid-call cannot receive the signal.
  - `service stop`/`restart` is refused for a protected list (dbus, logind,
    journald, udev, polkit, oomd, the common display managers) and for their
    sockets. The list is compared against every name systemctl resolves the
    unit to, so aliases such as `dbus-org.freedesktop.login1.service` and links
    such as `display-manager.service` are caught, and against what a socket or
    timer triggers.
  - `.target` units are never accepted, and the services behind reboot,
    poweroff, halt, kexec, suspend, hibernate, emergency and rescue are refused
    for every action including start.
  - PID 1 and below are always refused for everything.
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
- Stopping a service that is *not* on the protected list but that you
  personally depend on (NetworkManager, bluetooth, sshd). That is the feature.
- Renice, affinity and ionice have no owner check and are subject to the usual
  pid-reuse race. The worst case is a wrong process getting a different
  priority, which is why these three are not gated the way signals are.
- The last line of systemctl's or ionice's stderr is passed back to the caller
  in the JSON error. That can name units and paths; it cannot leak secrets.

This helper was reviewed once by an independent automated adversarial pass on
13 September 2026, which found the signal-by-pid bypass, the reboot target and
the alias gap described above; all three are fixed and pinned by tests. It has
not yet been reviewed by a second person.

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

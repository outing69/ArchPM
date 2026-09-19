"""install.sh's root part against a machine that has the package, and one
that does not. Run in a bubblewrap sandbox: a throwaway /usr/local, polkit
actions directory, /usr/lib overlay and /tmp, a fake home, uid 0 inside the
user namespace, and a sudo that just runs its command. Nothing reaches the
real machine. Skipped where bubblewrap or user namespaces are missing."""
from __future__ import annotations

import shutil
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
PKG_HELPER = "/usr/lib/archpm/archpm-helper"
LOCAL_HELPER = "/usr/local/lib/archpm/archpm-helper"
POLICY = "/usr/share/polkit-1/actions/io.github.outing69.archpm.policy"
CHECKOUT = "/home/sandbox/checkout"

# Inside the sandbox: lay the package's root part down, then run install.sh
# with the given options, then print what is left, one word per file.
SCRIPT = r'''
set -u
if [ "$WITH_PACKAGE" = yes ]; then
    mkdir -p /usr/lib/archpm
    cp "$CHECKOUT/archpm/root/helper.py" "$PKG_HELPER"; chmod 755 "$PKG_HELPER"
    sed "s|@HELPER@|$PKG_HELPER|" "$CHECKOUT/polkit/io.github.outing69.archpm.policy" > "$POLICY"
fi
if [ "$WITH_STRAY" = yes ]; then
    install -Dm755 "$CHECKOUT/archpm/root/helper.py" "$LOCAL_HELPER"
fi
for step in $STEPS; do
    (cd "$CHECKOUT" && ./install.sh "$step" >"/tmp/out-$step" 2>&1); echo "exit-$step=$?"
done
echo "pkg=$([ -e "$PKG_HELPER" ] && echo yes || echo no)"
echo "local=$([ -e "$LOCAL_HELPER" ] && echo yes || echo no)"
if [ -e "$POLICY" ]; then
    # whose policy: the exec.path annotation names the helper it launches
    grep -q "exec.path\">$PKG_HELPER<" "$POLICY" && echo "policy=package" || echo "policy=local"
else
    echo "policy=no"
fi
'''


def bwrap_works() -> bool:
    if shutil.which("bwrap") is None:
        return False
    try:
        proc = subprocess.run(
            ["bwrap", "--ro-bind", "/", "/", "--tmpfs", "/tmp", "--overlay-src", "/usr/lib",
             "--tmp-overlay", "/usr/lib", "--unshare-user", "--uid", "0", "--", "id", "-u"],
            capture_output=True, text=True, timeout=20, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return False
    return proc.returncode == 0 and proc.stdout.strip() == "0"


@unittest.skipUnless(bwrap_works(), "bubblewrap with user namespaces not available")
class RootPart(unittest.TestCase):
    def run_sandbox(self, steps: list[str], package: bool, stray: bool = False) -> dict[str, str]:
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / "home"
            bindir = Path(tmp) / "bin"
            (home / "checkout").mkdir(parents=True)
            bindir.mkdir()
            sudo = bindir / "sudo"
            sudo.write_text('#!/bin/sh\nexec "$@"\n')
            sudo.chmod(sudo.stat().st_mode | stat.S_IXUSR)
            argv = ["bwrap", "--ro-bind", "/", "/", "--dev", "/dev", "--proc", "/proc",
                    "--tmpfs", "/usr/local", "--tmpfs", "/usr/share/polkit-1/actions",
                    "--tmpfs", "/tmp", "--overlay-src", "/usr/lib", "--tmp-overlay", "/usr/lib",
                    "--tmpfs", "/home", "--bind", str(home), "/home/sandbox",
                    "--ro-bind", str(REPO), CHECKOUT,
                    # the shim's own directory may sit under /tmp, hidden by the tmpfs
                    "--ro-bind", str(bindir), "/home/sandbox/bin",
                    "--unshare-user", "--uid", "0", "--gid", "0", "--die-with-parent",
                    "--setenv", "PATH", "/home/sandbox/bin:/usr/bin:/bin",
                    "--setenv", "HOME", "/home/sandbox",
                    "--setenv", "XDG_RUNTIME_DIR", "/home/sandbox/run",
                    "--setenv", "XDG_CONFIG_HOME", "/home/sandbox/.config",
                    "--setenv", "CHECKOUT", CHECKOUT, "--setenv", "PKG_HELPER", PKG_HELPER,
                    "--setenv", "LOCAL_HELPER", LOCAL_HELPER, "--setenv", "POLICY", POLICY,
                    "--setenv", "WITH_PACKAGE", "yes" if package else "no",
                    "--setenv", "WITH_STRAY", "yes" if stray else "no",
                    "--setenv", "STEPS", " ".join(steps),
                    "--", "bash", "-c", SCRIPT]
            proc = subprocess.run(argv, capture_output=True, text=True, timeout=120, check=False)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        facts = dict(line.split("=", 1) for line in proc.stdout.splitlines() if "=" in line)
        for step in steps:
            self.assertEqual(facts.get(f"exit-{step}"), "0", f"{step} failed:\n{proc.stderr}")
        return facts

    def test_checkout_install_then_uninstall_root_removes_both_files(self):
        facts = self.run_sandbox(["--root", "--uninstall-root"], package=False)
        self.assertEqual((facts["local"], facts["policy"]), ("no", "no"))

    def test_checkout_install_then_full_uninstall_removes_both_files(self):
        facts = self.run_sandbox(["--root", "--uninstall"], package=False)
        self.assertEqual((facts["local"], facts["policy"]), ("no", "no"))

    def test_checkout_install_puts_both_files_in_place(self):
        facts = self.run_sandbox(["--root"], package=False)
        self.assertEqual((facts["local"], facts["policy"]), ("yes", "local"))

    def test_the_packages_policy_survives_a_full_uninstall(self):
        facts = self.run_sandbox(["--uninstall"], package=True)
        self.assertEqual((facts["pkg"], facts["policy"]), ("yes", "package"))

    def test_the_packages_policy_survives_uninstall_root(self):
        facts = self.run_sandbox(["--uninstall-root"], package=True)
        self.assertEqual((facts["pkg"], facts["policy"]), ("yes", "package"))

    def test_a_stray_local_helper_goes_and_the_packages_policy_stays(self):
        facts = self.run_sandbox(["--uninstall"], package=True, stray=True)
        self.assertEqual((facts["pkg"], facts["local"], facts["policy"]),
                         ("yes", "no", "package"))

    def test_install_root_refuses_over_the_package(self):
        facts = self.run_sandbox(["--root"], package=True)
        self.assertEqual((facts["local"], facts["policy"]), ("no", "package"))


if __name__ == "__main__":
    unittest.main()

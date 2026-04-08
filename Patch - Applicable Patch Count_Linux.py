#!/usr/bin/env python3
"""
Tanium Sensor: Patch - Applicable Patch Count (Linux)
Equivalent of: Patch - Applicable Patch Count_Win.vbs

Output contract (matches the Windows VBScript sensor):
  - Applicable patches found  -> plain integer string, e.g. "5"
  - No applicable patches     -> empty string  (Windows outputs VBScript Empty,
                                  which formatValue renders as "")
  - Scan data unavailable     -> "No Scan Results Found"
  - No patch source configured-> "No Patch Lists Found"
  - Tool / query failure      -> "Unable to load PatchLib"

Supported package managers (detected in priority order):
  apt-get / apt  (Debian, Ubuntu)
  dnf            (RHEL 8+, Fedora, CentOS Stream, Amazon Linux 2023)
  yum            (RHEL 6-7, CentOS 7, Amazon Linux 2)
  zypper         (SUSE, openSUSE)

Parameter (mirrors the Windows "showSuperseded" sensor parameter):
  Set env var TANIUM_SHOW_SUPERSEDED=1 to count ALL available updates.
  When unset or 0, only security-classified updates are counted on systems
  that expose a security filter (dnf, yum, zypper).  apt-based systems do
  not expose a security flag so all upgradable packages are always counted.
"""

import os
import shutil
import subprocess
import sys


# ---------------------------------------------------------------------------
# Subprocess helper
# ---------------------------------------------------------------------------

def _run(cmd: list, timeout: int = 120) -> tuple:
    """Return (returncode, stdout, stderr). Never raises."""
    try:
        r = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout,
        )
        return (
            r.returncode,
            r.stdout.decode("utf-8", errors="replace"),
            r.stderr.decode("utf-8", errors="replace"),
        )
    except subprocess.TimeoutExpired:
        return (-2, "", "timeout")
    except Exception as exc:
        return (-3, "", str(exc))


# ---------------------------------------------------------------------------
# Package-manager counters
# Each raises RuntimeError with a Windows-style message on failure,
# or returns an int >= 0 on success.
# ---------------------------------------------------------------------------

def _count_apt() -> int:
    """
    Use 'apt-get -s upgrade' (simulate/dry-run) to count pending upgrades.
    Parses the summary line: "N upgraded, N newly installed, ..."
    Falls back to 'apt list --upgradable' if apt-get is unavailable.
    """
    if shutil.which("apt-get"):
        rc, stdout, stderr = _run(
            ["apt-get", "-s", "upgrade", "-o", "Debug::NoLocking=true"]
        )
        if rc < 0:
            raise RuntimeError("Unable to load PatchLib")

        for line in stdout.splitlines():
            if "upgraded" in line and "newly installed" in line:
                parts = line.strip().split()
                try:
                    return int(parts[0]) + int(parts[3])
                except (ValueError, IndexError):
                    raise RuntimeError("Unable to load PatchLib")

        # Summary line not found; cache likely stale or never populated
        raise RuntimeError("No Scan Results Found")

    # apt-get not present; try plain apt
    if shutil.which("apt"):
        rc, stdout, stderr = _run(["apt", "list", "--upgradable", "--quiet=2"])
        if rc != 0:
            raise RuntimeError("Unable to load PatchLib")
        lines = [
            ln for ln in stdout.splitlines()
            if ln.strip() and not ln.lower().startswith("listing")
        ]
        return len(lines)

    raise RuntimeError("No Patch Lists Found")


def _count_dnf(show_superseded: bool) -> int:
    """
    Use 'dnf check-update' to count available updates.
    Returns 100 when updates exist, 0 when up-to-date, non-zero on error.
    """
    base_cmd = ["dnf", "check-update", "--quiet"]
    if not show_superseded:
        security_cmd = base_cmd + ["--security"]
        rc, stdout, stderr = _run(security_cmd, timeout=180)
        if rc in (0, 100):
            return _parse_check_update_output(stdout)
        # --security unsupported (older dnf) — fall through to all-updates query

    rc, stdout, stderr = _run(base_cmd, timeout=180)
    if rc not in (0, 100):
        if "No such command" in stderr or rc == -2:
            raise RuntimeError("No Scan Results Found")
        raise RuntimeError("Unable to load PatchLib")

    return _parse_check_update_output(stdout)


def _count_yum(show_superseded: bool) -> int:
    """Use 'yum check-update' (RHEL/CentOS <= 7)."""
    base_cmd = ["yum", "check-update", "--quiet"]
    if not show_superseded:
        security_cmd = base_cmd + ["--security"]
        rc, stdout, stderr = _run(security_cmd, timeout=180)
        if rc in (0, 100):
            return _parse_check_update_output(stdout)

    rc, stdout, stderr = _run(base_cmd, timeout=180)
    if rc not in (0, 100):
        raise RuntimeError("Unable to load PatchLib")

    return _parse_check_update_output(stdout)


def _count_zypper(show_superseded: bool) -> int:
    """
    Use 'zypper list-patches' (SUSE/openSUSE).
    zypper has an explicit patch concept; counts rows with status "needed".
    """
    if show_superseded:
        cmd = ["zypper", "--quiet", "list-patches", "--all"]
    else:
        cmd = ["zypper", "--quiet", "list-patches", "--category", "security"]

    rc, stdout, stderr = _run(cmd, timeout=180)
    if rc != 0:
        # Retry without category filter in case security patches unsupported
        rc, stdout, stderr = _run(
            ["zypper", "--quiet", "list-patches"], timeout=180
        )
        if rc != 0:
            raise RuntimeError("Unable to load PatchLib")

    count = 0
    for line in stdout.splitlines():
        lower = line.lower()
        if "| needed" in lower or "| needed |" in lower:
            count += 1
    return count


def _parse_check_update_output(stdout: str) -> int:
    """
    Parse yum/dnf check-update stdout.
    Each available update is a line of the form:
        package-name.arch    version    repo
    Skip headers, blank lines, and continuation/advisory lines.
    """
    skip_prefixes = (
        "last metadata",
        "loaded plugins",
        "loading mirror",
        "obsoleting",
        "security:",
        "warning",
        "error",
    )
    count = 0
    for line in stdout.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        lower = stripped.lower()
        if any(lower.startswith(p) for p in skip_prefixes):
            continue
        if line.startswith(" ") or line.startswith("\t"):
            # Continuation line (e.g. advisory description)
            continue
        count += 1
    return count


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    raw_flag = os.environ.get("TANIUM_SHOW_SUPERSEDED", "0").strip()
    show_superseded = raw_flag == "1"

    try:
        if shutil.which("apt-get") or shutil.which("apt"):
            count = _count_apt()
        elif shutil.which("dnf"):
            count = _count_dnf(show_superseded)
        elif shutil.which("yum"):
            count = _count_yum(show_superseded)
        elif shutil.which("zypper"):
            count = _count_zypper(show_superseded)
        else:
            # No recognized package manager — mirror "No Patch Lists Found"
            print("No Patch Lists Found")
            return

        # Match Windows output: Empty (blank) for 0, integer string for > 0
        print(str(count) if count > 0 else "")

    except RuntimeError as exc:
        print(str(exc))


if __name__ == "__main__":
    main()

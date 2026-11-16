#!/usr/bin/env python3
"""Local Windows user environment setup. No Dify/network operations."""
import argparse
import getpass
import json
import os
import re
import sys
import warnings

from kb_query import get_api_key, load_config, read_user_key


def save_user_key(value):
    import winreg
    # This is the native storage for Windows current-user environment variables.
    with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, "Environment", 0, winreg.KEY_SET_VALUE) as handle:
        winreg.SetValueEx(handle, "DIFY_KB_API_KEY", 0, winreg.REG_SZ, value)
    if read_user_key() != value:
        raise OSError("verification failed")


def main(argv=None):
    parser = argparse.ArgumentParser(description="Configure a Dify Knowledge API key in the local Windows user environment")
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--status", action="store_true", help="Report presence only; never display the value or access the network")
    modes.add_argument("--replace", action="store_true", help="Replace the saved key through interactive input")
    args = parser.parse_args(argv)
    existing = get_api_key()
    persistent = read_user_key()
    if args.status:
        print(json.dumps({"configured": bool(existing), "persistent_user_variable": bool(persistent),
                          "source": "process" if os.environ.get("DIFY_KB_API_KEY", "").strip()
                          else "windows_user" if persistent else "missing"}))
        return 0
    if sys.platform != "win32":
        print("Persistence is supported on Windows; on other systems configure the agent process environment.", file=sys.stderr)
        return 2
    if persistent and not args.replace:
        print("A key is already saved; no input is needed.")
        return 0
    if not sys.stdin.isatty():
        print("Run this yourself in a local interactive terminal; piped input, command-line keys, and chat input are not accepted.", file=sys.stderr)
        return 2
    try:
        load_config()
        print("Set up the Knowledge API connection once, then ask your assistant normally.")
        if existing and not args.replace:
            answer = input("A process key exists. Save it for future sessions? [y/N] ").strip().lower()
            if answer != "y":
                print("Configuration unchanged.")
                return 0
            value = existing
        else:
            with warnings.catch_warnings():
                warnings.simplefilter("error", getpass.GetPassWarning)
                value = getpass.getpass("Paste the Knowledge API key here (hidden; never paste into chat): ").strip()
        if not value or not value.isascii() or re.search(r"\s|[\x00-\x1f\x7f]", value):
            print("The key is empty or contains invalid characters; nothing was saved.", file=sys.stderr)
            return 2
        save_user_key(value)
        os.environ["DIFY_KB_API_KEY"] = value
        print("Key saved. Return to your assistant to continue.")
        return 0
    except (EOFError, KeyboardInterrupt):
        print("Setup interrupted; the assistant can still check key status.", file=sys.stderr)
        return 2
    except getpass.GetPassWarning:
        print("Hidden input is unavailable; use a local interactive terminal. No key was read.", file=sys.stderr)
        return 2
    except (OSError, ValueError):
        print("Could not save the key; check the local user environment.", file=sys.stderr)
        return 2


if __name__ == "__main__":
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    sys.exit(main())

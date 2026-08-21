#!/usr/bin/env python3
"""Backup Encryption / Decryption Utility

Encrypts backup files with age (modern, simple) or GPG (legacy).
Used by backup.py and restore_verify.py.

Usage:
    python scripts/backup_encrypt.py encrypt backups/backup_20240101.sql.gz
    python scripts/backup_encrypt.py decrypt backups/backup_20240101.sql.gz.age
"""
import os
import sys
import subprocess
import argparse
from pathlib import Path


def encrypt_age(input_path: Path, recipient: str = None, passphrase: str = None) -> Path:
    """Encrypt file with age (age-encryption.org)."""
    output_path = input_path.with_suffix(input_path.suffix + ".age")

    if passphrase:
        # Symmetric encryption with passphrase
        cmd = ["age", "--passphrase", "--output", str(output_path), str(input_path)]
        env = os.environ.copy()
        env["AGE_PASSPHRASE"] = passphrase
    elif recipient:
        # Public key encryption
        cmd = ["age", "--recipient", recipient, "--output", str(output_path), str(input_path)]
        env = os.environ
    else:
        raise ValueError("Either --recipient or --passphrase required for encryption")

    result = subprocess.run(cmd, capture_output=True, text=True, env=env)
    if result.returncode != 0:
        raise RuntimeError(f"age encryption failed: {result.stderr}")

    return output_path


def decrypt_age(input_path: Path, passphrase: str = None) -> Path:
    """Decrypt age-encrypted file."""
    if not input_path.suffix == ".age":
        raise ValueError("Input file must have .age extension")

    output_path = input_path.with_suffix("")  # Remove .age

    if passphrase:
        cmd = ["age", "--decrypt", "--passphrase", "--output", str(output_path), str(input_path)]
        env = os.environ.copy()
        env["AGE_PASSPHRASE"] = passphrase
    else:
        cmd = ["age", "--decrypt", "--output", str(output_path), str(input_path)]
        env = os.environ

    result = subprocess.run(cmd, capture_output=True, text=True, env=env)
    if result.returncode != 0:
        raise RuntimeError(f"age decryption failed: {result.stderr}")

    return output_path


def encrypt_gpg(input_path: Path, recipient: str = None, passphrase: str = None) -> Path:
    """Encrypt file with GPG (legacy)."""
    output_path = input_path.with_suffix(input_path.suffix + ".gpg")

    if passphrase:
        cmd = [
            "gpg", "--batch", "--yes", "--symmetric",
            "--cipher-algo", "AES256",
            "--passphrase", passphrase,
            "--output", str(output_path),
            str(input_path),
        ]
    elif recipient:
        cmd = [
            "gpg", "--batch", "--yes", "--encrypt",
            "--recipient", recipient,
            "--output", str(output_path),
            str(input_path),
        ]
    else:
        raise ValueError("Either --recipient or --passphrase required for GPG encryption")

    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"GPG encryption failed: {result.stderr}")

    return output_path


def decrypt_gpg(input_path: Path, passphrase: str = None) -> Path:
    """Decrypt GPG-encrypted file."""
    if not input_path.suffix == ".gpg":
        raise ValueError("Input file must have .gpg extension")

    output_path = input_path.with_suffix("")

    cmd = [
        "gpg", "--batch", "--yes", "--decrypt",
        "--output", str(output_path),
    ]
    if passphrase:
        cmd.extend(["--passphrase", passphrase])
    cmd.append(str(input_path))

    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"GPG decryption failed: {result.stderr}")

    return output_path


def main():
    parser = argparse.ArgumentParser(description="Encrypt/decrypt backup files")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # Encrypt
    enc = subparsers.add_parser("encrypt", help="Encrypt a backup file")
    enc.add_argument("input", type=Path, help="Input file (e.g., backup.sql.gz)")
    enc.add_argument("--method", choices=["age", "gpg"], default="age", help="Encryption method")
    enc.add_argument("--recipient", help="Age/GPG recipient (public key)")
    enc.add_argument("--passphrase", help="Passphrase for symmetric encryption")

    # Decrypt
    dec = subparsers.add_parser("decrypt", help="Decrypt a backup file")
    dec.add_argument("input", type=Path, help="Input file (.age or .gpg)")
    dec.add_argument("--passphrase", help="Passphrase for symmetric decryption")

    args = parser.parse_args()

    if not args.input.exists():
        print(f"ERROR: Input file not found: {args.input}", file=sys.stderr)
        return 1

    try:
        if args.command == "encrypt":
            if args.method == "age":
                out = encrypt_age(args.input, args.recipient, args.passphrase)
            else:
                out = encrypt_gpg(args.input, args.recipient, args.passphrase)
            print(f"Encrypted: {out}")
        else:
            if args.input.suffix == ".age":
                out = decrypt_age(args.input, args.passphrase)
            elif args.input.suffix == ".gpg":
                out = decrypt_gpg(args.input, args.passphrase)
            else:
                print(f"ERROR: Unknown encryption format: {args.input.suffix}", file=sys.stderr)
                return 1
            print(f"Decrypted: {out}")
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
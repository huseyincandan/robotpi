#!/usr/bin/env python3
"""Build MotorEspS3 on the Pi; upload only with explicit board/port settings."""
import argparse
import json
from pathlib import Path
import shutil
import socket
import subprocess

ROOT = Path(__file__).resolve().parents[1]
LOCAL = ROOT / '.arduino-local'
FQBN = 'esp32:esp32:esp32s3:FlashSize=4M,PSRAM=disabled,PartitionScheme=default,FlashMode=qio'
CORE_VERSION = '3.3.10'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['build', 'upload', 'boards'])
    parser.add_argument('--fqbn', help='Arduino board identifier including flash/PSRAM/partition options')
    parser.add_argument('--port', help='USB serial device or S3 IP address')
    parser.add_argument('--protocol', choices=['serial', 'network'])
    args = parser.parse_args()
    cli = LOCAL / 'bin' / 'arduino-cli'
    if not cli.exists():
        parser.error('Arduino CLI is missing from .arduino-local/bin')
    command = [str(cli), '--config-file', str(LOCAL / 'arduino-cli.yaml')]
    if args.action == 'boards':
        subprocess.run(command + ['board', 'list'], check=True)
        return
    if args.action == 'upload' and not args.port:
        parser.error('upload requires --port')
    upload_port = args.port
    if args.action == 'upload' and args.protocol == 'network':
        # Arduino CLI's network protocol expects a discovered address, and may
        # not resolve an ESP mDNS .local hostname as port metadata. Resolve it
        # here on the Pi, where its mDNS resolver is configured.
        try:
            upload_port = socket.getaddrinfo(
                args.port, None, family=socket.AF_INET,
                type=socket.SOCK_STREAM,
            )[0][4][0]
            print(f'Network upload target: {args.port} -> {upload_port}')
        except socket.gaierror as exc:
            parser.error(
                f'Cannot resolve network target {args.port!r}: {exc}. '
                'Use the S3 IPv4 address with --port.'
            )
    installed = json.loads(subprocess.check_output(command + ['core', 'list', '--json']))
    platforms = installed.get('platforms', [])
    if not any(p.get('id') == 'esp32:esp32' and p.get('installed_version') == CORE_VERSION for p in platforms):
        parser.error('Install esp32:esp32@' + CORE_VERSION + ' before building')
    fqbn = args.fqbn or FQBN
    sketch = LOCAL / 'sketch' / 'MotorEspS3'
    sketch.mkdir(parents=True, exist_ok=True)
    shutil.copy2(ROOT / 'MotorEspS3.ino', sketch / 'MotorEspS3.ino')
    output = LOCAL / 'firmware'
    # Always build before upload so an older binary cannot be selected silently.
    subprocess.run(command + ['compile', '--fqbn', fqbn, '--jobs', '2',
                              '--output-dir', str(output), str(sketch)], check=True)
    if args.action == 'upload':
        upload = command + ['upload', '--fqbn', fqbn, '--port', upload_port,
                            '--input-dir', str(output)]
        if args.protocol:
            upload += ['--protocol', args.protocol]
        # CLI requests OTA credentials interactively; no passwords stored here.
        subprocess.run(upload + [str(sketch)], check=True)


if __name__ == '__main__':
    main()

#!/usr/bin/env python3
"""Explicit offline enrollment. WAV inputs must be mono PCM16, 16 kHz."""
import argparse
import json
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from services.speaker_identity import SpeakerIdentityService


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='action', required=True)
    sub.add_parser('list')
    add = sub.add_parser('enroll')
    add.add_argument('--name', required=True)
    add.add_argument('--wake', nargs='+', required=True)
    add.add_argument('--command', nargs='+', required=True)
    delete = sub.add_parser('delete')
    delete.add_argument('id')
    args = parser.parse_args()
    service = SpeakerIdentityService()
    try:
        if args.action == 'enroll':
            print(service.enroll(args.name, args.wake, args.command))
        elif args.action == 'delete':
            if not service.delete(args.id):
                parser.error('Unknown speaker ID')
        else:
            print(json.dumps(service.status(), ensure_ascii=False, indent=2))
    finally:
        service.close()


if __name__ == '__main__':
    main()

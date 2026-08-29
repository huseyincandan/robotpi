import argparse
import json
import urllib.error
import urllib.request

from config import APP


def request(method, path):

    url = f"http://127.0.0.1:{APP['PORT']}{path}"
    request_data = urllib.request.Request(
        url,
        method=method
    )

    with urllib.request.urlopen(
        request_data,
        timeout=5
    ) as response:
        return json.loads(
            response.read().decode("utf-8")
        )


def main():

    parser = argparse.ArgumentParser(
        description="Control HamsiBot music playback"
    )
    parser.add_argument(
        "command",
        choices=[
            "status",
            "stop",
            "next"
        ]
    )
    args = parser.parse_args()

    try:
        if args.command == "status":
            result = request(
                "GET",
                "/music/status"
            )

        else:
            result = request(
                "POST",
                f"/music/{args.command}"
            )

    except urllib.error.URLError as exc:
        raise SystemExit(
            f"Music control failed: {exc}"
        ) from exc

    print(
        json.dumps(
            result,
            ensure_ascii=False
        )
    )


if __name__ == "__main__":
    main()

import argparse
import json
import sys
from pathlib import Path

from dotenv import load_dotenv

from judge.judges import run_judge
from server.signing import verify


def main():
    load_dotenv(Path(__file__).resolve().parent / ".env")
    parser = argparse.ArgumentParser(description="Judge a Family AI Game Day video.")
    parser.add_argument("video", nargs="?", help="Input video file")
    parser.add_argument("--game", choices=["football", "majlis_freeze", "say_it_right", "hand_duel", "bucket_toss"])
    parser.add_argument("--config", help="JSON configuration file")
    parser.add_argument("--out", default="report.json", help="Where to save the signed report")
    parser.add_argument("--verify", dest="verify_file", help="Verify an existing signed report JSON")
    args = parser.parse_args()
    if args.verify_file:
        try:
            data = json.loads(Path(args.verify_file).read_text(encoding="utf-8"))
            report, signature = data["report"], data["signature"]
        except (OSError, json.JSONDecodeError, KeyError, TypeError) as exc:
            print(f"Could not read a signed report: {exc}", file=sys.stderr)
            return 2
        valid = verify(report, signature)
        print("Signature verified." if valid else "Signature invalid.")
        return 0 if valid else 1
    if not args.video or not args.game or not args.config:
        parser.error("video, --game and --config are required unless --verify is used")
    try:
        config = json.loads(Path(args.config).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"Could not read judge config: {exc}", file=sys.stderr)
        return 2
    config.setdefault("session_id", "standalone")
    config.setdefault("game", args.game)
    if config["game"] != args.game:
        parser.error("--game must match config.game")
    try:
        result = run_judge(args.game, args.video, config)
    except (OSError, RuntimeError, ValueError) as exc:
        print(f"Judge failed: {exc}", file=sys.stderr)
        return 1
    Path(args.out).write_text(json.dumps({"report": result["report"], "signature": result["signature"]}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(result["report"]["summary"])
    print(f"SHA-256: {result['report']['video_sha256']}")
    print(f"Signed report: {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

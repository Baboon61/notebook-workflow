"""Compact CLI summaries never include notebook outputs or source code."""

import argparse
import json
import sys
from pathlib import Path

from .core import WorkflowError, abort, apply, prepare, refresh_state, resume, restore, review, sessions, status
from .editor import after_apply, before_apply, before_prepare, record_editor


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    start = commands.add_parser("prepare", help="export the saved notebook for AI assistance")
    start.add_argument("notebook")
    start.add_argument("--session-root")
    start.add_argument("--dependency-policy", choices=("conservative", "identified", "changed-only"),
                       default="conservative", help="clear dependent outputs; conservative clears later cells when uncertain")
    start.add_argument("--editor", choices=("auto", "required", "off"), default="auto")
    finish = commands.add_parser("apply", help="apply script edits to the existing notebook")
    finish.add_argument("session")
    finish.add_argument("--dry-run", action="store_true")
    finish.add_argument("--editor", choices=("auto", "required", "off"), default="auto")
    for name in ("status", "review", "abort"):
        commands.add_parser(name).add_argument("session")
    for name in ("resume", "restore", "refresh"):
        command = commands.add_parser(name)
        command.add_argument("session")
        command.add_argument("--editor", choices=("auto", "required", "off"), default="auto")
    listing = commands.add_parser("sessions", help="find editing sessions for a notebook or project")
    listing.add_argument("path", nargs="?", default=".")
    listing.add_argument("--session-root")
    args = parser.parse_args(argv)
    try:
        if args.command == "prepare":
            descriptor = before_prepare(str(Path(args.notebook).resolve()), args.editor)
            result = prepare(args.notebook, session_root=args.session_root, dependency_policy=args.dependency_policy)
            record_editor(result["session"], descriptor)
            result["editor"] = {"connected": descriptor is not None, "saved": descriptor is not None}
        elif args.command == "apply":
            descriptor = before_apply(args.session, args.editor)
            result = apply(args.session, dry_run=args.dry_run)
            if not args.dry_run:
                result["editor"] = after_apply(descriptor, result)
        elif args.command == "restore":
            descriptor = before_apply(args.session, args.editor)
            result = restore(args.session)
            result["editor"] = after_apply(descriptor, {**result, "outputs_cleared": []})
        elif args.command == "refresh":
            result = refresh_state(args.session)
            descriptor = before_apply(args.session, args.editor)
            result["editor"] = after_apply(descriptor, result)
        elif args.command == "resume":
            result = resume(args.session)
            descriptor = before_apply(args.session, args.editor)
            record_editor(result["session"], descriptor)
            result["editor"] = {"connected": descriptor is not None}
        elif args.command == "sessions":
            result = sessions(args.path, session_root=args.session_root)
        elif args.command == "review":
            result = review(args.session)
        elif args.command == "abort":
            result = abort(args.session)
        else:
            result = status(args.session)
    except (WorkflowError, OSError, ValueError) as error:
        print(json.dumps({"error": str(error)}), file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

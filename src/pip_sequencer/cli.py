import argparse
import sys
import os
from .recorder import (
    record_install,
    record_uninstall,
    replay_install,
    export_sequence,
    _is_uv_available # Import check function for early exit
)
from .history import get_history_path, get_export_path, EXPORT_FILE_NAME

# --- Argument Definition Helpers ---

def add_common_install_args(parser):
    """Helper to add common args for install commands."""
    parser.add_argument(
        "packages",
        nargs='+',
        help="Package(s) or requirements file(s) to install"
    )
    parser.add_argument(
        'pip_args',
        nargs=argparse.REMAINDER,
        help="Arguments to pass directly to the backend install command (prefix with '--', e.g., -- --no-cache-dir)"
    )

def add_common_uninstall_args(parser):
    """Helper to add common args for uninstall commands."""
    parser.add_argument(
        "packages",
        nargs='+',
        help="Package(s) to uninstall"
    )
    parser.add_argument(
        'pip_args',
        nargs=argparse.REMAINDER,
        help="Arguments to pass directly to the backend uninstall command (prefix with '--', e.g., -- --no-save)"
    )

def add_common_replay_args(parser):
    """Helper to add common args for replay commands."""
    parser.add_argument(
        "--from-export",
        metavar="EXPORT_FILE",
        nargs='?', # Optional argument for the path
        const=get_export_path(), # Default value if flag is present *without* a value
        default=None, # Default if flag is *absent*
        help=f"Replay from a filtered export file instead of the full history file. If path omitted, defaults to '{get_export_path()}'.",
    )
    parser.add_argument(
        "--start", type=int, default=1, metavar="N",
        help="Sequence number (from the file being replayed) to start replay from."
    )
    parser.add_argument(
        "--end", type=int, default=None, metavar="N",
        help="Sequence number (from the file being replayed) to end replay at (inclusive). Default: replay to the end."
    )

# --- Main Function ---

def main():
    # Main parser for pseq/pip-sequencer
    parser = argparse.ArgumentParser(
        # Use 'pseq' as the primary program name in help messages
        prog='pseq',
        description="Record, replay, and export pip/uv installation sequences with user-selectable backend.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
        # Update epilog examples to use 'pseq'
        epilog="""Examples:
  pseq install requests              # Install requests using pip backend (default)
  pseq uv install flask              # Install flask using uv backend
  pseq pip uninstall django         # Uninstall django using pip backend explicitly
  pseq replay --from-export        # Replay exported sequence using pip backend (default)
  pseq uv replay --start 5         # Replay steps 5+ from history using uv backend
  pseq export -o my_sequence.json  # Export current state sequence
        """
    )
    parser.add_argument(
        "--file", "-f",
        metavar="HISTORY_FILE",
        help=f"Path to the sequence history file used for recording and potentially replaying/exporting.",
        default=get_history_path()
    )

    # --- Top-level subparsers: uv, pip, or direct action (defaults to pip) ---
    subparsers = parser.add_subparsers(
        dest="backend_or_command",
        required=True,
        metavar='COMMAND | BACKEND',
        title='Commands and Backends',
        description=f"""Choose an action like 'install', 'uninstall', 'replay', 'export'
(these default to using the 'pip' backend for installation/uninstallation),
or explicitly specify the backend ('uv' or 'pip') before the action.
Example: 'pseq uv install ...' or 'pseq install ...' (uses pip).""",
        help="Action command or explicit backend selection."
    )

    # --- Define actions (install, uninstall, replay) ---
    def add_actions_to_parser(target_parser, backend_name="pip"):
        """Adds install, uninstall, replay subparsers to a given parser."""
        action_subparsers = target_parser.add_subparsers(
            dest="command",
            required=True,
            metavar='ACTION',
            title=f'Actions (using {backend_name} backend)',
            help=f"Action to perform using the '{backend_name}' backend."
        )

        # Install Action
        parser_install = action_subparsers.add_parser(
            "install",
            help=f"Install packages and record using '{backend_name}'.",
            description=f"Wraps '{backend_name} install'. Records packages and versions to the history file."
        )
        add_common_install_args(parser_install)

        # Uninstall Action
        parser_uninstall = action_subparsers.add_parser(
            "uninstall",
             help=f"Uninstall packages and record using '{backend_name}'.",
             description=f"Wraps '{backend_name} uninstall'. Records requested packages to the history file."
        )
        add_common_uninstall_args(parser_uninstall)

        # Replay Action
        parser_replay = action_subparsers.add_parser(
            "replay",
             help=f"Replay installs from history or export using '{backend_name}'.",
             description=f"Reads install sequences and re-installs packages sequentially using '{backend_name}'."
        )
        add_common_replay_args(parser_replay)

    # --- Backend Subparsers ---

    # UV Backend
    parser_uv = subparsers.add_parser(
        'uv',
        help="Use 'uv' backend for subsequent actions (install, uninstall, replay). Requires 'uv' in PATH.",
        description="Prefix actions with 'uv' to use the uv package manager backend."
    )
    add_actions_to_parser(parser_uv, backend_name="uv") # Add install/uninstall/replay under 'uv'

    # PIP Backend (Explicit)
    parser_pip = subparsers.add_parser(
        'pip',
        help="Explicitly use 'pip' backend for subsequent actions (install, uninstall, replay).",
        description="Prefix actions with 'pip' to explicitly use the pip package manager backend."
    )
    add_actions_to_parser(parser_pip, backend_name="pip") # Add install/uninstall/replay under 'pip'


    # --- Direct Actions (Default to PIP backend) ---
    # These are treated as if 'pip' was specified first.

    # Install (Defaults to pip)
    parser_install_direct = subparsers.add_parser(
        'install',
        help="Install packages and record (uses 'pip' backend by default)."
    )
    add_common_install_args(parser_install_direct)

    # Uninstall (Defaults to pip)
    parser_uninstall_direct = subparsers.add_parser(
        'uninstall',
        help="Uninstall packages and record (uses 'pip' backend by default)."
    )
    add_common_uninstall_args(parser_uninstall_direct)

    # Replay (Defaults to pip)
    parser_replay_direct = subparsers.add_parser(
        'replay',
        help="Replay installs from history or export (uses 'pip' backend by default)."
    )
    add_common_replay_args(parser_replay_direct)

    # Export (Doesn't need backend choice, add directly)
    parser_export = subparsers.add_parser(
        'export',
        help="Generate sequenced export file and requirements_frozen.txt.",
        description="Reads history, checks current packages, and creates export files. Backend independent."
    )
    parser_export.add_argument(
        "--output", "-o",
        metavar="EXPORT_FILE",
        help=f"Path to save the exported sequence file.",
        default=get_export_path()
    )

    # --- Parse Arguments ---
    args = parser.parse_args()

    # --- Determine Effective Backend and Command ---
    effective_backend = 'pip' # Default
    actual_command = None

    if args.backend_or_command in ['uv', 'pip']:
        # Backend was specified first
        effective_backend = args.backend_or_command
        actual_command = args.command # The action is under the backend subparser
    elif args.backend_or_command in ['install', 'uninstall', 'replay', 'export']:
        # Direct command used, backend defaults to 'pip' for relevant commands
        actual_command = args.backend_or_command
        # effective_backend remains 'pip' unless command is 'export'
    else:
        # Should not happen with required=True, but defensive check
        parser.error(f"Internal error: Could not determine command from '{args.backend_or_command}'. Please report this.")


    # --- Execute Logic ---
    history_file_to_use = args.file
    exit_code = 0

    try:
        # --- Early exit if uv is required but unavailable ---
        # Check only if uv is explicitly chosen for relevant commands
        if effective_backend == 'uv' and actual_command in ['install', 'uninstall', 'replay']:
            if not _is_uv_available():
                 print(f"Error: Backend 'uv' was specified for command '{actual_command}', but 'uv' is not found in your PATH.", file=sys.stderr)
                 print("Please install uv or use the 'pip' backend.", file=sys.stderr)
                 sys.exit(1)

        # --- Dispatch to appropriate function ---
        if actual_command == "install":
            pip_options = args.pip_args
            # Correctly handle case where REMIANDER might capture '--'
            if pip_options and pip_options[0] == '--':
                pip_options = pip_options[1:]
            # Pass effective_backend to recorder function
            if not record_install(effective_backend, args.packages, pip_args=pip_options, history_path=history_file_to_use):
                 exit_code = 1

        elif actual_command == "uninstall":
            pip_options = args.pip_args
            if pip_options and pip_options[0] == '--':
                pip_options = pip_options[1:]
            # Pass effective_backend to recorder function
            if not record_uninstall(effective_backend, args.packages, pip_args=pip_options, history_path=history_file_to_use):
                 exit_code = 1

        elif actual_command == "replay":
            replay_target = args.from_export
            # Pass effective_backend to recorder function
            # Replay function handles its own errors/status printing
            replay_install(
                effective_backend, # Pass chosen backend
                history_path=history_file_to_use if replay_target is None else None,
                start_step=args.start,
                end_step=args.end,
                target_file=replay_target
            )

        elif actual_command == "export":
            # Export function handles its own errors/status printing
            export_sequence(
                history_path=history_file_to_use,
                export_file_path=args.output
            )

    except Exception as e:
        print(f"\nAn unexpected error occurred: {e}", file=sys.stderr)
        # Consider adding traceback print here for debugging development versions
        # import traceback
        # traceback.print_exc()
        exit_code = 1

    sys.exit(exit_code)


if __name__ == "__main__":
    main()
import json
import os
from datetime import datetime, timezone

HISTORY_FILE_NAME = ".pip_sequence.json"
EXPORT_FILE_NAME = "pip_sequence_export.json" # New file for export

def get_history_path(path=None):
    """Determines the path to the history file."""
    if path:
        return path
    # Default to current working directory
    return os.path.join(os.getcwd(), HISTORY_FILE_NAME)

def get_export_path(path=None):
    """Determines the path for the exported sequence file."""
    if path:
        return path
    # Default to current working directory
    return os.path.join(os.getcwd(), EXPORT_FILE_NAME)

def load_history(path=None):
    """Loads the installation history from the JSON file."""
    history_path = get_history_path(path)
    if not os.path.exists(history_path):
        return []
    try:
        with open(history_path, 'r', encoding='utf-8') as f:
            # Add robustness: Handle empty file case
            content = f.read()
            if not content:
                return []
            return json.loads(content)
    except (json.JSONDecodeError, IOError) as e:
        print(f"Warning: Could not load history file {history_path}. Error: {e}")
        return []

def save_history(history, path=None):
    """Saves the installation history to the JSON file."""
    history_path = get_history_path(path)
    try:
        # Sort by sequence just in case
        history.sort(key=lambda x: x.get('sequence', 0))
        with open(history_path, 'w', encoding='utf-8') as f:
            json.dump(history, f, indent=2)
    except IOError as e:
        print(f"Error: Could not save history file {history_path}. Error: {e}")

# Modified to include action
def _add_history_entry(action, command_args, details, path=None):
    """Internal function to add a generic history entry."""
    history = load_history(path)
    next_sequence = (history[-1]['sequence'] + 1) if history else 1

    entry = {
        "sequence": next_sequence,
        "action": action,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "command": command_args,
    }
    entry.update(details) # Add action-specific details

    history.append(entry)
    save_history(history, path)
    print(f"Recorded {action} step {next_sequence} to {get_history_path(path)}")

# Specific function for install
def add_install_entry(command_args, installed_packages, path=None):
    """Adds a new install entry to the history file."""
    details = {"installed": installed_packages} # List of {"package": name, "version": ver}
    _add_history_entry("install", command_args, details, path=path)

# Specific function for uninstall
def add_uninstall_entry(command_args, uninstalled_requested, path=None):
    """Adds a new uninstall entry to the history file."""
    details = {"uninstalled_requested": uninstalled_requested} # List of package names
    _add_history_entry("uninstall", command_args, details, path=path)

def save_exported_sequence(sequence, path=None):
    """Saves the filtered sequence to the export file."""
    export_path = get_export_path(path)
    try:
        with open(export_path, 'w', encoding='utf-8') as f:
            json.dump(sequence, f, indent=2)
        print(f"Exported filtered installation sequence to {export_path}")
    except IOError as e:
        print(f"Error: Could not save export file {export_path}. Error: {e}")
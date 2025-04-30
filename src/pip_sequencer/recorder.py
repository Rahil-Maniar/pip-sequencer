import subprocess
import sys
import os
import pkg_resources
import json
import shutil # For shutil.which

from .history import (
    add_install_entry,
    add_uninstall_entry,
    load_history,
    save_exported_sequence,
    get_history_path,
    get_export_path,
    EXPORT_FILE_NAME
)

# --- Helper to check if uv is available ---
def _is_uv_available():
    """Checks if the 'uv' executable is available in the PATH."""
    return shutil.which('uv') is not None

# --- get_package_version (Remains the same) ---
def get_package_version(package_name):
    """Gets the installed version of a package."""
    try:
        # Normalize name for lookup using pkg_resources standard
        normalized_name = pkg_resources.safe_name(package_name).lower()
        return pkg_resources.get_distribution(normalized_name).version
    except pkg_resources.DistributionNotFound:
        # print(f"Debug: Version not found for '{package_name}' (normalized: '{normalized_name}')") # Optional debug
        return None
    except Exception as e:
        print(f"Warning: Error getting version for '{package_name}': {e}")
        return None


# --- run_pip_install (MODIFIED to accept backend) ---
def run_pip_install(backend, packages_to_install, pip_args=None):
    """Runs the actual install command using the specified backend ('pip' or 'uv')."""
    if backend == 'uv':
        uv_path = shutil.which('uv') # Get path again for execution
        if not uv_path:
            print("Error: Backend 'uv' requested, but 'uv' command not found in PATH.", file=sys.stderr)
            return False
        base_command = [uv_path, 'pip'] # Use 'uv pip ...'
        backend_name = 'uv'
    elif backend == 'pip':
        base_command = [sys.executable, '-m', 'pip']
        backend_name = 'pip'
    else:
        # Should not happen if CLI parsing is correct, but defensive check
        print(f"Error: Invalid backend specified: {backend}", file=sys.stderr)
        return False

    command = list(base_command) # Create a copy
    command.append("install")

    if pip_args:
        command.extend(pip_args)
    command.extend(packages_to_install)

    print(f"Running command via {backend_name}: {' '.join(command)}")
    try:
        # Use encoding for cross-platform compatibility with captured output
        result = subprocess.run(command, check=True, capture_output=True, text=True, encoding='utf-8')
        print(result.stdout)
        if result.stderr:
            print(f"--- {backend_name} stderr ---", file=sys.stderr)
            print(result.stderr, file=sys.stderr)
            print(f"--- end {backend_name} stderr ---", file=sys.stderr)
        return True
    except subprocess.CalledProcessError as e:
        print(f"Error: {backend_name} install failed with exit code {e.returncode}", file=sys.stderr)
        print(f"--- {backend_name} stdout ---", file=sys.stderr)
        print(e.stdout, file=sys.stderr)
        print(f"--- {backend_name} stderr ---", file=sys.stderr)
        print(e.stderr, file=sys.stderr)
        print("--- end output ---", file=sys.stderr)
        return False
    except Exception as e:
        print(f"Error: Failed to execute {backend_name} install command. Error: {e}", file=sys.stderr)
        return False

# --- record_install (MODIFIED to accept backend) ---
def record_install(backend, packages_to_install, pip_args=None, history_path=None):
    """Runs pip install via specified backend and records."""
    # Combine packages and args for recording the original command
    original_command_args = packages_to_install + (pip_args if pip_args else [])

    # Identify explicitly requested package names (best effort)
    requested_base_names = set()
    for pkg_spec in packages_to_install:
        # Ignore arguments/options starting with '-' unless part of a valid spec (e.g., URL, path)
        if pkg_spec.startswith('-') and not any(c in pkg_spec for c in":/@"):
             # Likely an option like -r, -e, -c, --upgrade etc. skip parsing as package name
             continue
        try:
            # pkg_resources Requirement parsing is good for standard names/specs
            req = pkg_resources.Requirement.parse(pkg_spec)
            requested_base_names.add(req.project_name.lower())
        except ValueError:
             # Handle complex cases like URLs, file paths, git links etc.
             # We won't try complex parsing here, just record the command
             # The version lookup later will try based on assumption or fail gracefully
             print(f"Info: Could not parse '{pkg_spec}' as standard requirement. Will attempt version lookup if install succeeds.")
             # Basic fallback: try to guess name before first standard specifier/separator
             name_part = pkg_spec
             # Prioritize separators that strongly indicate end of name
             for char in ['==', '<=', '>=', '<', '>', '~=', '===', '!=', '[', '#', '@', ' ']:
                 if char in name_part:
                     name_part = name_part.split(char, 1)[0].strip()
                     break
             # Further cleanup for potential file paths or URLs
             if os.path.sep in name_part or ':' in name_part:
                 # Too complex, don't add a likely incorrect base name
                 pass
             elif name_part:
                requested_base_names.add(name_part.lower())

    # Calls run_pip_install with the backend
    if not run_pip_install(backend, packages_to_install, pip_args):
        print("Installation failed. Nothing recorded.")
        return False # Crucially return False here

    # --- Version Recording Logic ---
    installed_info = []
    print("Recording versions for explicitly requested/identified packages...")
    # Rescan installed packages *after* the install command finishes
    pkg_resources.working_set = pkg_resources.WorkingSet()

    # Filter out duplicates and attempt version lookup
    unique_requested_names = set()
    for name in requested_base_names:
        # Normalize name for consistent checking
        normalized_name = pkg_resources.safe_name(name).lower()
        if normalized_name: # Avoid empty strings if parsing failed badly
            unique_requested_names.add(normalized_name)

    for name in unique_requested_names:
        version = get_package_version(name) # Uses normalized name internally
        if version:
            # Store the original name/spec if possible, fallback to normalized?
            # Let's store normalized name for consistency in replay keys
            installed_info.append({"package": name, "version": version})
        else:
            print(f"Could not determine installed version for '{name}' after install. It will not be added to the sequence record with a version.")
            # Optionally record without version? For now, skip to ensure replay works cleanly.
            # installed_info.append({"package": name, "version": None})

    # --- History Saving Logic ---
    # Backend choice isn't saved, only the command and outcome
    if installed_info:
         add_install_entry(original_command_args, installed_info, path=history_path)
    elif unique_requested_names: # If names requested but versions not found
         print("Install command ran, but version lookup failed for requested packages. Recording command without versions.")
         add_install_entry(original_command_args, [], path=history_path) # Record generic entry
    else: # Covers case where run_pip_install succeeded but no packages requested (e.g. -r file only)
         print("Install command ran, but no specific packages were explicitly requested or resolved for version recording.")
         add_install_entry(original_command_args, [], path=history_path) # Record generic entry

    return True # Indicate command ran and recording was attempted


# --- run_pip_uninstall (MODIFIED to accept backend) ---
def run_pip_uninstall(backend, packages_to_uninstall, pip_args=None):
    """Runs the actual uninstall command using the specified backend ('pip' or 'uv')."""
    if backend == 'uv':
        uv_path = shutil.which('uv') # Get path again for execution
        if not uv_path:
            print("Error: Backend 'uv' requested, but 'uv' command not found in PATH.", file=sys.stderr)
            return False
        base_command = [uv_path, 'pip']
        backend_name = 'uv'
    elif backend == 'pip':
        base_command = [sys.executable, '-m', 'pip']
        backend_name = 'pip'
    else:
        print(f"Error: Invalid backend specified: {backend}", file=sys.stderr)
        return False

    command = list(base_command)
    command.append("uninstall")
    command.append("-y") # Add -y automatically

    if pip_args:
        # Filter out -y if user accidentally provided it (case-insensitive)
        filtered_args = [arg for arg in pip_args if arg.lower() != '-y' and arg.lower() != '--yes']
        command.extend(filtered_args)
    # Add packages *after* options
    command.extend(packages_to_uninstall)

    print(f"Running command via {backend_name}: {' '.join(command)}")
    try:
        result = subprocess.run(command, check=True, capture_output=True, text=True, encoding='utf-8')
        print(result.stdout)
        if result.stderr:
            print(f"--- {backend_name} stderr ---", file=sys.stderr)
            print(result.stderr, file=sys.stderr)
            print(f"--- end {backend_name} stderr ---", file=sys.stderr)
        return True
    except subprocess.CalledProcessError as e:
        # Handle cases where uninstall reports packages not found gracefully
        stderr_lower = e.stderr.lower()
        if "not installed" in stderr_lower or "no files were found" in stderr_lower:
             print(f"Warning: {backend_name} uninstall reported some packages not installed (exit code {e.returncode}). Proceeding.", file=sys.stderr)
             # Print output for debugging if needed
             # print(f"--- {backend_name} stdout ---", file=sys.stderr); print(e.stdout, file=sys.stderr)
             # print(f"--- {backend_name} stderr ---", file=sys.stderr); print(e.stderr, file=sys.stderr)
             return True # Treat as success for recording
        else:
            print(f"Error: {backend_name} uninstall failed with exit code {e.returncode}", file=sys.stderr)
            print(f"--- {backend_name} stdout ---", file=sys.stderr); print(e.stdout, file=sys.stderr)
            print(f"--- {backend_name} stderr ---", file=sys.stderr); print(e.stderr, file=sys.stderr)
            print("--- end output ---", file=sys.stderr)
            return False # Genuine error
    except Exception as e:
        print(f"Error: Failed to execute {backend_name} uninstall command. Error: {e}", file=sys.stderr)
        return False

# --- record_uninstall (MODIFIED to accept backend) ---
def record_uninstall(backend, packages_to_uninstall, pip_args=None, history_path=None):
    """Runs pip uninstall via specified backend and records."""
    # Parse requested packages (excluding options)
    requested_packages = [pkg for pkg in packages_to_uninstall if not pkg.startswith('-')]
    # Combine packages and args for recording the original command
    original_command_args = packages_to_uninstall + (pip_args if pip_args else [])

    # Calls run_pip_uninstall with the backend
    if not run_pip_uninstall(backend, packages_to_uninstall, pip_args):
        print("Uninstall command failed or encountered significant errors. Nothing recorded.")
        return False # Return False on failure

    # Add entry to history using the *requested* packages list
    add_uninstall_entry(original_command_args, requested_packages, path=history_path)
    return True # Return True on success


# --- replay_install (MODIFIED to accept backend) ---
def replay_install(backend, history_path=None, start_step=1, end_step=None, target_file=None):
    """Replays the installation sequence using the specified backend."""
    # --- Load History/Export File ---
    is_export_file = False
    history = []
    if target_file:
        is_export_file = os.path.basename(target_file) == EXPORT_FILE_NAME
        replay_file_path = target_file
        print(f"Attempting to replay from specified file: {replay_file_path}")
        try:
            with open(replay_file_path, 'r', encoding='utf-8') as f:
                 content = f.read()
                 history = [] if not content else json.loads(content)
        except FileNotFoundError:
             print(f"Error: Replay file not found: {replay_file_path}"); return
        except (json.JSONDecodeError, IOError) as e:
             print(f"Error: Could not load/parse replay file {replay_file_path}: {e}"); return
    else:
        replay_file_path = get_history_path(history_path)
        print(f"Attempting to replay from history file: {replay_file_path}")
        history = load_history(path=history_path)
        is_export_file = False

    if not history:
        print(f"Replay file '{replay_file_path}' empty/not loaded. Nothing to replay."); return

    print(f"Starting replay using '{backend}' backend from file: {replay_file_path}") # Mention backend

    # --- Determine Sequence Range & Initialize ---
    max_step = max((entry.get('sequence', 0) for entry in history), default=0)
    effective_start_step = max(1, start_step)
    effective_end_step = end_step if end_step is not None else float('inf')
    steps_processed_count = 0
    last_step_processed = 0
    replay_failed = False

    # --- Loop Through Entries ---
    for entry in history:
        seq = entry.get('sequence', 0)
        if not (effective_start_step <= seq <= effective_end_step):
            continue

        action = entry.get('action')
        if not is_export_file and action != "install":
            print(f"Skipping step {seq}: Action '{action}' not replayed from history file.")
            continue

        print(f"\n--- Replaying Step {seq} (using {backend}) ---")

        # Determine package list ('installed' for history, 'packages' for export)
        installed_list = entry.get("installed") if not is_export_file else entry.get("packages")
        if not isinstance(installed_list, list) or not installed_list:
            print(f"Skipping step {seq}: No valid package list found."); continue

        # Construct package==version strings
        packages_to_install_specs = []
        valid_step = True
        for item in installed_list:
            if not isinstance(item, dict):
                 print(f"Warning: Skipping invalid item in step {seq}: {item}"); valid_step = False; break
            pkg = item.get('package')
            ver = item.get('version')
            if pkg and ver: packages_to_install_specs.append(f"{pkg}=={ver}")
            elif pkg: print(f"Warning: Version missing for '{pkg}' in step {seq}. Installing without constraint."); packages_to_install_specs.append(pkg)
            else: print(f"Warning: Skipping entry missing package name in step {seq}: {item}"); valid_step = False; break
        if not valid_step: print(f"Skipping step {seq} due to invalid item format."); continue
        if not packages_to_install_specs: print(f"Skipping step {seq}: No packages formatted for installation."); continue

        # --- Install Packages Sequentially for this Step ---
        step_success = True
        for package_spec in packages_to_install_specs:
             print(f"Attempting to install: {package_spec}")
             # Pass the backend down to run_pip_install
             if not run_pip_install(backend, [package_spec]): # Pass backend here!
                 print(f"Error: Failed to install '{package_spec}' from step {seq} using {backend}. Stopping replay.")
                 step_success = False
                 replay_failed = True
                 break # Stop installing within this step

        if not step_success:
             break # Stop the entire replay

        steps_processed_count += 1
        last_step_processed = seq
        print(f"--- Step {seq} completed ---")
        if end_step is not None and seq >= end_step: # Use >= in case end_step is skipped but reached
            print(f"Reached or passed specified end step {end_step}. Stopping replay.")
            break

    # --- Final Replay Summary ---
    print("\n--- Replay Summary ---")
    if steps_processed_count > 0:
        range_desc = f"from sequence {effective_start_step}"
        if end_step is not None: range_desc += f" up to {min(last_step_processed, end_step)}"
        elif last_step_processed > 0: range_desc += f" up to {last_step_processed}"
        else: range_desc = f"for sequence step {effective_start_step}"
        status = "partially completed" if replay_failed else "completed"
        print(f"Replay {status} using '{backend}' backend. Processed {steps_processed_count} step(s) {range_desc} from {replay_file_path}.")
        if replay_failed: print("Replay stopped due to an error during installation.")
    else:
         range_desc = f"in range {effective_start_step}"
         if end_step is not None: range_desc += f" to {end_step}"
         else: range_desc += " onwards"
         print(f"No eligible install steps found {range_desc} in {replay_file_path}.")
    print("----------------------")


# --- export_sequence (Remains the same, backend independent) ---
def export_sequence(history_path=None, export_file_path=None):
    """Exports the sequence of currently installed packages based on history."""
    history = load_history(path=history_path)
    if not history:
        print(f"History file '{get_history_path(history_path)}' is empty or not found. Cannot export.")
        return

    print("Getting list of currently installed packages...")
    pkg_resources.working_set = pkg_resources.WorkingSet() # Ensure it's fresh
    installed_packages_map = {} # Store as {normalized_name: distribution}
    try:
        for dist in pkg_resources.working_set:
             installed_packages_map[dist.key] = dist # key is already normalized name
    except Exception as e:
        print(f"Error getting installed packages via pkg_resources: {e}. Cannot perform export accurately.")
        return

    if not installed_packages_map:
        print("Warning: No installed packages found in the current environment.")

    print(f"Found {len(installed_packages_map)} installed packages.")

    filtered_sequence = []
    original_sequences_included = set()
    packages_added_to_export = set() # Track normalized names added

    print("Filtering history based on currently installed packages...")
    for entry in history:
        # Only consider 'install' actions from the history
        if entry.get("action") != "install":
            continue

        seq = entry.get("sequence")
        installed_list = entry.get("installed", [])

        if not isinstance(installed_list, list) or not installed_list:
            continue

        # Check if *all* packages explicitly recorded in this step are still present
        # Add the packages the *first* time we encounter them in the history.
        all_present = True
        packages_in_this_step_to_add = [] # Store tuples of (normalized_name, original_dict)

        for item in installed_list:
            if not isinstance(item, dict): continue # Skip malformed
            pkg_name = item.get("package")
            if not pkg_name: continue # Skip malformed

            normalized_name = pkg_resources.safe_name(pkg_name).lower()

            # Check 1: Is the package currently installed?
            if normalized_name not in installed_packages_map:
                all_present = False
                break

            # Check 2: Only add if not already added to export list
            if normalized_name not in packages_added_to_export:
                 packages_in_this_step_to_add.append((normalized_name, item))

        # If step is valid and has packages we haven't added yet
        if all_present and packages_in_this_step_to_add:
            valid_packages_for_export_entry = []
            for norm_name, item_dict in packages_in_this_step_to_add:
                 if norm_name not in packages_added_to_export: # Double check just in case
                     valid_packages_for_export_entry.append(item_dict)
                     packages_added_to_export.add(norm_name) # Mark as added

            if valid_packages_for_export_entry:
                export_entry = {
                    "sequence": seq,
                    "packages": valid_packages_for_export_entry
                }
                filtered_sequence.append(export_entry)
                original_sequences_included.add(seq)

    if not filtered_sequence:
        print("No install steps from the history correspond to currently installed packages, or packages were already covered by earlier steps.")
    else:
        # Sort by original sequence number
        filtered_sequence.sort(key=lambda x: x.get('sequence', 0))
        print(f"Generated export sequence with {len(filtered_sequence)} steps including {len(packages_added_to_export)} unique packages (original sequence numbers: {sorted(list(original_sequences_included))}).")
        save_exported_sequence(filtered_sequence, path=export_file_path)

    # --- Generate standard requirements.txt using pip freeze ---
    freeze_path = "requirements_frozen.txt"
    print(f"\nGenerating standard freeze file (no sequence) using 'pip freeze' to {freeze_path}...")
    try:
        with open(freeze_path, 'w', encoding='utf-8') as f:
            result = subprocess.run([sys.executable, "-m", "pip", "freeze"], stdout=f, stderr=subprocess.PIPE, check=True, text=True, encoding='utf-8')
            if result.stderr:
                 print("--- pip freeze stderr ---", file=sys.stderr)
                 print(result.stderr, file=sys.stderr)
                 print("--- end pip freeze stderr ---", file=sys.stderr)
        print(f"Standard frozen requirements saved to {freeze_path}")
    except FileNotFoundError:
         print(f"Error: Could not find '{sys.executable} -m pip'. Is pip installed correctly?")
    except subprocess.CalledProcessError as e:
        print(f"Error running pip freeze (exit code {e.returncode}):", file=sys.stderr)
        print(e.stderr, file=sys.stderr)
    except Exception as e:
        print(f"Could not generate standard requirements.txt: {e}")
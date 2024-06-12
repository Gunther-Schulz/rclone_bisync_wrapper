import yaml
import os
import sys
import subprocess
import argparse
from datetime import datetime
import signal
import atexit

# TODO: Add option for which side to prefer when doing a resync
# TODO: Maybe try one of the speed-up options for bisync for gunther

# Note: Send a SIGINT twice to force exit

# Set the locale to UTF-8 to handle special characters correctly
os.environ['LC_ALL'] = 'C.UTF-8'

# Default arguments
dry_run = False
force_resync = False
console_log = False
specific_folder = None

# Initialize variables
base_dir = os.path.join(os.environ['HOME'], '.rclone_bisync')
sync_base_dir = base_dir.rstrip('/')
pid_file = os.path.join(base_dir, 'rclone_bisync.pid')
config_file = os.path.join(base_dir, 'rclone_bisync.yaml')
resync_status_file_name = ".resync_status"
sync_status_file_name = ".bisync_status"

# Global counter for CTRL-C presses
ctrl_c_presses = 0

# Global list to keep track of subprocesses
subprocesses = []


# Handle CTRL-C
def signal_handler(signal_received, frame):
    global ctrl_c_presses
    ctrl_c_presses += 1

    if ctrl_c_presses > 1:
        print('Multiple CTRL-C detected. Forcing exit.')
        os._exit(1)  # Force exit immediately

    print('SIGINT or CTRL-C detected. Exiting gracefully.')
    for proc in subprocesses:
        if proc.poll() is None:  # Subprocess is still running
            proc.send_signal(signal.SIGINT)
        proc.wait()  # Wait indefinitely until subprocess terminates
    remove_pid_file()
    sys.exit(0)


# Set the signal handler
signal.signal(signal.SIGINT, signal_handler)


# Logging
def log_message(message):
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    log_entry = f"{timestamp} - {message}\n"
    with open(log_file_path, 'a') as f:
        f.write(log_entry)
    if console_log:
        print(log_entry, end='')


# Logging errors
def log_error(message):
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    error_entry = f"{timestamp} - ERROR: {message}\n"
    with open(log_file_path, 'a') as f:
        f.write(error_entry)
    with open(error_log_file_path, 'a') as f:
        f.write(f"{timestamp} - {message}\n")
    if console_log:
        print(error_entry, end='')


# Check if the script is already running
def check_pid():
    if os.path.exists(pid_file):
        with open(pid_file, 'r') as f:
            pid = f.read().strip()
        # Check if the process is still running
        try:
            os.kill(int(pid), 0)
            # log_error(f"Script is already running with PID {pid}.")
            sys.exit(1)
        except OSError:
            # log_message(f"Removing stale PID file {pid_file}.")
            os.remove(pid_file)

    with open(pid_file, 'w') as f:
        f.write(str(os.getpid()))

    # Register the cleanup function to remove the PID file at exit
    atexit.register(remove_pid_file)


# Remove the PID file
def remove_pid_file():
    if os.path.exists(pid_file):
        os.remove(pid_file)
        # log_message("PID file removed.")


# Parse command line arguments
def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument('folder', nargs='?', default=None,
                        help='Specify a folder to sync (optional).')
    parser.add_argument('-d', '--dry-run', action='store_true',
                        help='Perform a dry run without making any changes.')
    parser.add_argument('--resync', action='store_true',
                        help='Force a resynchronization, ignoring previous sync status.')
    parser.add_argument('--console-log', action='store_true',
                        help='Print log messages to the console in addition to the log files.')
    args, unknown = parser.parse_known_args()
    global dry_run, force_resync, console_log, specific_folder
    dry_run = args.dry_run
    force_resync = args.resync
    console_log = args.console_log
    specific_folder = args.folder


# Check if the required tools are installed
def check_tools():
    required_tools = ["rclone", "mkdir", "grep", "awk", "find", "md5sum"]
    for tool in required_tools:
        if subprocess.call(['which', tool], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL) != 0:
            print(f"{tool} could not be found, please install it.",
                  file=sys.stderr)
            sys.exit(1)


# Ensure the rclone directory exists.
def ensure_rclone_dir():
    rclone_dir = os.path.join(os.environ['HOME'], '.cache', 'rclone', 'bisync')
    if not os.access(rclone_dir, os.W_OK):
        os.makedirs(rclone_dir, exist_ok=True)
        os.chmod(rclone_dir, 0o777)


# Load the configuration file
def load_config():
    # Add log_dir to globals
    global sync_base_dir, filter_file, max_delete, sync_dirs, log_dir
    if not os.path.exists(config_file):
        print("Configuration file not found. Please ensure it exists at:", config_file)
        sys.exit(1)
    with open(config_file, 'r') as f:
        config = yaml.safe_load(f)
    sync_base_dir = config['sync_base_dir']
    filter_file = config['filter_file']
    max_delete = config['max_delete']
    sync_dirs = config['sync_dirs']
    log_dir = config['log_dir']


# Ensure log directory exists
def ensure_log_directory():
    os.makedirs(log_dir, exist_ok=True)
    global log_file_path, error_log_file_path
    log_file_path = os.path.join(log_dir, "bisync.log")
    error_log_file_path = os.path.join(log_dir, "bisync_error.log")


# Calculate the MD5 of a file
def calculate_md5(file_path):
    result = subprocess.run(['md5sum', file_path],
                            capture_output=True, text=True)
    return result.stdout.split()[0]


# Handle filter changes
def handle_filter_changes():
    stored_md5_file = os.path.join(base_dir, '.filter_md5')
    if os.path.exists(filter_file):
        current_md5 = calculate_md5(filter_file)
        if os.path.exists(stored_md5_file):
            with open(stored_md5_file, 'r') as f:
                stored_md5 = f.read().strip()
        else:
            stored_md5 = ""
        if current_md5 != stored_md5:
            with open(stored_md5_file, 'w') as f:
                f.write(current_md5)
            log_message("Filter file has changed. A resync is required.")
            global force_resync
            force_resync = True


# Handle the exit code of rclone
def handle_rclone_exit_code(return_code, local_path, sync_type):
    messages = {
        0: "completed successfully. Exit code 0",
        1: "Non-critical error. A rerun may be successful. Exit code 1",
        2: "Critically aborted. Did you add a 'RCLONE_TEST' file to both local and remote? You can add those files using the command 'touch RCLONE_TEST' in both the local and remote target directories. For example to add to remote: rclone touch remote_profile:/MyStuff/RCLONE_TEST and to local: rclone touch /home/user/sync_folders/MyStuff/RCLONE_TEST",
        3: "Directory not found. Exit code 3",
        4: "File not found. Exit code 4",
        5: "Temporary error. More retries might fix this issue. Exit code 5",
        6: "Less serious errors. Exit code 6",
        7: "Fatal error. Retries will not fix this issue. Exit code 7",
        8: "Transfer limit exceeded. Exit code 8",
        9: "successful but no files were transferred. Exit code 9",
        10: "Duration limit exceeded. Exit code 10"
    }
    message = messages.get(return_code, "failed with an unknown error code")
    if return_code == 0 or return_code == 9:
        log_message(f"{sync_type} {message} for {local_path}.")
        return "COMPLETED"
    else:
        log_error(f"{sync_type} {message} for {local_path}.")
        return "FAILED"


# Perform a bisync
def bisync(remote_path, local_path):
    log_message(f"Bisync started for {local_path} at {
                datetime.now()}" + (" - Performing a dry run" if dry_run else ""))

    rclone_args = [
        'rclone', 'bisync', remote_path, local_path,
        '--retries', '3',
        '--low-level-retries', '10',
        '--exclude', '*.tmp',
        '--exclude', '*.log',
        '--exclude', resync_status_file_name,
        '--exclude', sync_status_file_name,
        '--log-file', os.path.join(log_dir, 'sync.log'),
        '--log-level', 'INFO' if dry_run else 'ERROR',
        '--conflict-resolve', 'newer',
        '--conflict-loser', 'num',
        '--conflict-suffix', 'rc-conflict',
        '--max-delete', str(max_delete),
        '--recover',
        '--resilient',
        '--max-lock', '15m',
        '--compare', 'size,modtime,checksum',
        '--create-empty-src-dirs',
        '--track-renames',
        '--check-access'
    ]
    if os.path.exists(filter_file):
        rclone_args.extend(['--exclude-from', filter_file])
    if dry_run:
        rclone_args.append('--dry-run')

    result = subprocess.run(rclone_args, capture_output=True, text=True)
    sync_result = handle_rclone_exit_code(
        result.returncode, local_path, "Bisync")
    log_message(f"Bisync status for {local_path}: {sync_result}")
    write_sync_status(local_path, sync_result)


def resync(remote_path, local_path):
    if force_resync:
        log_message("Force resync requested.")
    else:
        sync_status = read_resync_status(local_path)
        if sync_status == "COMPLETED":
            log_message("No resync necessary. Skipping.")
            return sync_status
        elif sync_status == "IN_PROGRESS":
            log_message("Resuming interrupted resync.")
        elif sync_status == "FAILED":
            log_error(
                f"Previous resync failed. Manual intervention required. Status: {sync_status}. Check the logs at {log_file_path} to fix the issue and remove the file {os.path.join(local_path, resync_status_file_name)} to start a new resync. Exiting...")
            sys.exit(1)

    log_message(f"Resync started for {local_path} at {
                datetime.now()}" + (" - Performing a dry run" if dry_run else ""))

    write_resync_status(local_path, "IN_PROGRESS")

    rclone_args = [
        'rclone', 'bisync', remote_path, local_path,
        '--resync',
        '--log-file', os.path.join(log_dir, 'sync.log'),
        '--log-level', 'INFO' if dry_run else 'ERROR',
        '--retries', '3',
        '--low-level-retries', '10',
        '--error-on-no-transfer',
        '--exclude', '*.tmp',
        '--exclude', '*.log',
        '--exclude', resync_status_file_name,
        '--exclude', sync_status_file_name,
        '--max-delete', str(max_delete),
        '--recover',
        '--resilient',
        '--max-lock', '15m',
        '--compare', 'size,modtime,checksum',
        '--create-empty-src-dirs',
        '--check-access'
    ]
    if os.path.exists(filter_file):
        rclone_args.extend(['--exclude-from', filter_file])
    if dry_run:
        rclone_args.append('--dry-run')

    result = subprocess.run(rclone_args, capture_output=True, text=True)
    sync_result = handle_rclone_exit_code(
        result.returncode, local_path, "Resync")
    log_message(f"Resync status for {local_path}: {sync_result}")
    write_resync_status(local_path, sync_result)

    return sync_result


# Write the sync status
def write_sync_status(local_path, sync_status):
    sync_status_file = os.path.join(local_path, sync_status_file_name)
    if not dry_run:
        with open(sync_status_file, 'w') as f:
            f.write(sync_status)


# Write the resync status
def write_resync_status(local_path, sync_status):
    sync_status_file = os.path.join(local_path, resync_status_file_name)
    if not dry_run:
        with open(sync_status_file, 'w') as f:
            f.write(sync_status)


# Read the resync status
def read_resync_status(local_path):
    sync_status_file = os.path.join(local_path, resync_status_file_name)
    if os.path.exists(sync_status_file):
        with open(sync_status_file, 'r') as f:
            return f.read().strip()
    return "NONE"


# Ensure the local directory exists. If not, create it.
def ensure_local_directory(local_path):
    if not os.path.exists(local_path):
        os.makedirs(local_path)
        log_message(f"Local directory {local_path} created.")


# Perform the sync operations
def perform_sync_operations():
    if specific_folder and specific_folder not in sync_dirs:
        log_error(f"Folder '{
                  specific_folder}' is not configured in sync directories. Make sure it is in the list of sync_dirs in the configuration file at {config_file}.")
        return  # Exit the function if the specified folder is not in the configuration

    for key, value in sync_dirs.items():
        if specific_folder and specific_folder != key:
            continue  # Skip folders not specified by the user
        local_path = os.path.join(sync_base_dir, value['local'])
        remote_path = f"{value['rclone_remote']}:{value['remote']}"
        ensure_local_directory(local_path)
        if resync(remote_path, local_path) == "COMPLETED":
            bisync(remote_path, local_path)


def main():
    check_pid()
    parse_args()
    check_tools()
    ensure_rclone_dir()
    load_config()
    ensure_log_directory()  # Ensure the log directory exists after loading the configuration
    handle_filter_changes()
    perform_sync_operations()


if __name__ == "__main__":
    main()
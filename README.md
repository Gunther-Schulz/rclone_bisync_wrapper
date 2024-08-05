# RClone BiSync Script

This Python script provides a robust solution for bidirectional synchronization of files between a local directory and a remote storage supported by RClone. It includes features such as dry runs, forced resynchronization, and detailed logging.

## Features

- **Bidirectional Synchronization**: Synchronize files between local and remote directories.
- **Dry Run Option**: Test synchronization without making actual changes.
- **Forced Resynchronization**: Ignore previous sync statuses and force a new sync.
- **Detailed Logging**: Log all operations, with separate logs for errors.
- **Configurable**: Configuration through a YAML file.
- **Signal Handling**: Graceful shutdown on SIGINT (CTRL-C).

## Opinionated Settings

To keep the script simple and robust, this script uses some opinionated settings for the `rclone bisync` command that are not exposed in the configuration file. These settings are chosen to provide a robust and safe synchronization process that should work for most use cases:

- `--conflict-resolve newer`: Resolves conflicts by keeping the newer file.
- `--conflict-loser num`: Renames the losing file in a conflict by appending a number.
- `--conflict-suffix rc-conflict`: Appends 'rc-conflict' to the filename of the losing file in a conflict.
- `--recover`: Attempts to recover from a failed sync.
- `--resilient`: Continues the sync even if some files can't be transferred.
- `--create-empty-src-dirs`: Creates empty directories on the destination if they exist in the source.
- `--track-renames`: Tracks file renames to optimize sync performance.
- `--check-access`: Checks that rclone has proper access to the remote storage before starting the sync.
- `--compare size,modtime,checksum`: Compares files using size, modification time, and checksum to determine if they're different.

These settings are designed to handle conflicts gracefully, improve reliability, and optimize the synchronization process. The comparison method ensures a thorough check of file differences. These options are not configurable to ensure consistent behavior across all synchronization operations.

## Prerequisites

Ensure you have `rclone` installed on your system along with other required tools like `mkdir`, `grep`, `awk`, `find`, and `md5sum`. These tools are necessary for the script to function correctly.

## Installation

1. Clone the repository or download the script to your local machine.
2. Ensure that the script is executable:

```bash
chmod +x rclone_bisync.py
```

3. Create the configuration directory:

```bash
mkdir -p ~/.config/rclone_bisync
```

## Configuration

Before running the script, you must set up the configuration file (`~/.config/rclone_bisync/config.yaml`). This file contains all necessary settings for the synchronization process.

### Configuration File Structure

Here is a detailed explanation of the configuration file:

- **max_delete_percentage**: Maximum percentage of files that can be deleted in a single sync operation. This is a safety measure to prevent data loss.
- **local_base_path**: The base directory on your local machine where synchronization folders are located.
- **exclusion_rules_file**: Path to a file containing patterns to exclude from synchronization.
- **log_directory**: Directory where log files will be stored.
- **max_cpu_usage_percent**: CPU usage limit as a percentage.
- **max_lock**: Maximum time to hold the sync lock, preventing concurrent syncs.
- **log_level**: Default log level (can be DEBUG, INFO, NOTICE, ERROR, or FATAL).
- **sync_paths**: A dictionary of synchronization pairs with details for local and remote directories.

#### Example Configuration

```yaml
local_base_path: /home/g/hidrive
exclusion_rules_file: /home/g/hidrive/filter.txt
log_directory: /home/g/hidrive/logs
max_delete: 5
max_lock: 15m
log_level: INFO
max_cpu_usage_percent: 100
sync_paths:
  documents:
    local: "Docs"
    rclone_remote: "remoteName"
    remote: "RemoteDocs"
```

### Important Notes

- **sync_base_dir**: This should be an absolute path.
- **filter_file**: This file should contain one pattern per line, which defines which files to exclude from sync. For me details refer to the rclone documenatation. Example:

```bash
.*\.txt$
.*\.doc$
```

- **sync_dirs**: Each entry under this key represents a pair of directories to be synchronized. `local` is a subdirectory under `sync_base_dir`, and `remote` is the path on the remote storage.

## Usage

Run the script using the following command:

```bash
python rclone_bisync.py [options]
```

### Command Line Options

- **folder**: Specify a particular folder to sync (optional).
- **-d, --dry-run**: Perform a dry run.
- **--resync**: Force a resynchronization.
- **--force-bisync**: Force a bisync. This option is only applicable if a specific folder is specified.
- **--console-log**: Enable logging to the console. Only wrapper messages are logged to the console, not the detailed log messages from rclone.

## Logs

Logs are stored in the `logs` directory within the base directory specified in the configuration file. There are separate logs for general operations and errors.

## Handling Errors

If the script encounters critical errors, it logs them and may require manual intervention. Check the error log file `sync_error.log` for concise information and the main logfile `sync.log` for detailed information.

## Automating Synchronization with Systemd

To run the RClone BiSync script periodically using systemd, follow these steps:

1. **Create a service file template**:
   Create a new file `/etc/systemd/system/rclone-bisync@.service` with the following content:

   ```ini
   [Unit]
   Description=Rclone Bisync Service for %i
   After=network-online.target
   Wants=network-online.target

   [Service]
   Type=oneshot
   ExecStart=/usr/bin/rclone-bisync %i
   User=your_username

   [Install]
   WantedBy=multi-user.target
   ```

   Replace `your_username` with the user you want the script to run as.

2. **Create a timer file template**:
   Create a new file `/etc/systemd/system/rclone-bisync@.timer` with the following content:

   ```ini
   [Unit]
   Description=Run Rclone Bisync for %i periodically

   [Timer]
   OnBootSec=${RCLONE_BISYNC_DEFAULT_ONBOOTSEC}
   OnUnitActiveSec=${RCLONE_BISYNC_DEFAULT_ONUNITACTIVESEC}
   OnBootSec=${RCLONE_BISYNC_%i_ONBOOTSEC}
   OnUnitActiveSec=${RCLONE_BISYNC_%i_ONUNITACTIVESEC}
   Persistent=true

   [Install]
   WantedBy=timers.target
   ```

3. **Configure the timer settings**:
   Edit the configuration file located at `/etc/rclone-bisync/timer.conf`:

   ```ini
   # Default settings
   RCLONE_BISYNC_DEFAULT_ONBOOTSEC=15min
   RCLONE_BISYNC_DEFAULT_ONUNITACTIVESEC=1h

   # Specific settings for sync_path entries
   RCLONE_BISYNC_documents_ONBOOTSEC=15min
   RCLONE_BISYNC_documents_ONUNITACTIVESEC=1h

   RCLONE_BISYNC_photos_ONBOOTSEC=30min
   RCLONE_BISYNC_photos_ONUNITACTIVESEC=2h

   RCLONE_BISYNC_music_ONBOOTSEC=1h
   RCLONE_BISYNC_music_ONUNITACTIVESEC=4h
   ```

   Adjust these values as needed for each sync_path entry. The default settings will be used for any sync_path that doesn't have specific settings.

4. **Enable and start the timers**:
   For each sync_path entry, run the following commands to enable and start the timer:

   ```bash
   sudo systemctl daemon-reload
   sudo systemctl enable rclone-bisync@documents.timer
   sudo systemctl start rclone-bisync@documents.timer
   sudo systemctl enable rclone-bisync@photos.timer
   sudo systemctl start rclone-bisync@photos.timer
   sudo systemctl enable rclone-bisync@music.timer
   sudo systemctl start rclone-bisync@music.timer
   ```

5. **Check the status of the timers**:
   You can check the status of your timers with:

   ```bash
   sudo systemctl status rclone-bisync@documents.timer
   sudo systemctl status rclone-bisync@photos.timer
   sudo systemctl status rclone-bisync@music.timer
   ```

6. **Apply configuration changes**:
   If you modify the `/etc/rclone-bisync/timer.conf` file, reload the systemd daemon and restart the timers:

   ```bash
   sudo systemctl daemon-reload
   sudo systemctl restart rclone-bisync@documents.timer
   sudo systemctl restart rclone-bisync@photos.timer
   sudo systemctl restart rclone-bisync@music.timer
   ```

This setup will run your rclone bisync script periodically for each sync_path entry using systemd, with different intervals for each entry. The use of a separate configuration file allows you to easily adjust the timing without directly editing systemd files. The default settings will be used for any sync_path that doesn't have specific settings defined.

## Contributing

Contributions to the script are welcome. Please fork the repository, make your changes, and submit a pull request.

## License

Specify the license under which the script is released.

---

For more details on `rclone` and its capabilities, visit the [official RClone documentation](https://rclone.org/docs/).

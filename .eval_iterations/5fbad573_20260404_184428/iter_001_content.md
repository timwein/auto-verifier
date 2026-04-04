```bash
#!/bin/bash

# ==============================================================================
# PostgreSQL Backup Script with S3 Upload, Rotation, and Notifications
# ==============================================================================
# Author: Database Administrator
# Version: 1.0
# Description: Automated PostgreSQL backup with AWS S3 storage, rotation,
#              comprehensive logging, and multi-channel error notifications
# ==============================================================================

set -euo pipefail  # Exit on errors, undefined vars, and pipe failures

# ==============================================================================
# CONFIGURATION SECTION
# ==============================================================================

# Database Configuration
readonly DB_HOST="${DB_HOST:-localhost}"
readonly DB_PORT="${DB_PORT:-5432}"
readonly DB_NAME="${DB_NAME:-}"
readonly DB_USER="${DB_USER:-postgres}"
readonly DB_PASSWORD="${DB_PASSWORD:-}"

# AWS S3 Configuration
readonly S3_BUCKET="${S3_BUCKET:-}"
readonly S3_PREFIX="${S3_PREFIX:-postgresql-backups}"
readonly S3_REGION="${S3_REGION:-us-east-1}"
readonly AWS_ACCESS_KEY_ID="${AWS_ACCESS_KEY_ID:-}"
readonly AWS_SECRET_ACCESS_KEY="${AWS_SECRET_ACCESS_KEY:-}"

# Backup Configuration
readonly BACKUP_DIR="${BACKUP_DIR:-/tmp/pg_backups}"
readonly RETENTION_DAYS="${RETENTION_DAYS:-7}"
readonly COMPRESSION="${COMPRESSION:-gzip}"
readonly PARALLEL_JOBS="${PARALLEL_JOBS:-2}"
readonly BACKUP_FORMAT="${BACKUP_FORMAT:-custom}"  # custom or plain

# Logging Configuration
readonly LOG_DIR="${LOG_DIR:-/var/log/postgresql-backup}"
readonly LOG_LEVEL="${LOG_LEVEL:-INFO}"
readonly MAX_LOG_SIZE="${MAX_LOG_SIZE:-10485760}"  # 10MB in bytes

# Notification Configuration
readonly ENABLE_EMAIL="${ENABLE_EMAIL:-true}"
readonly EMAIL_RECIPIENTS="${EMAIL_RECIPIENTS:-admin@example.com}"
readonly SMTP_SERVER="${SMTP_SERVER:-localhost}"

readonly ENABLE_SLACK="${ENABLE_SLACK:-false}"
readonly SLACK_WEBHOOK_URL="${SLACK_WEBHOOK_URL:-}"
readonly SLACK_CHANNEL="${SLACK_CHANNEL:-#alerts}"

readonly ENABLE_WEBHOOK="${ENABLE_WEBHOOK:-false}"
readonly WEBHOOK_URL="${WEBHOOK_URL:-}"

# Script Metadata
readonly SCRIPT_NAME="$(basename "$0")"
readonly SCRIPT_PID="$$"
readonly TIMESTAMP="$(date '+%Y-%m-%d_%H-%M-%S')"
readonly LOG_FILE="$LOG_DIR/backup_${TIMESTAMP}.log"

# ==============================================================================
# VALIDATION AND PREREQUISITES
# ==============================================================================

validate_config() {
    local errors=()

    # Required parameters validation
    [[ -z "$DB_NAME" ]] && errors+=("DB_NAME is required")
    [[ -z "$S3_BUCKET" ]] && errors+=("S3_BUCKET is required")
    [[ -z "$AWS_ACCESS_KEY_ID" ]] && errors+=("AWS_ACCESS_KEY_ID is required")
    [[ -z "$AWS_SECRET_ACCESS_KEY" ]] && errors+=("AWS_SECRET_ACCESS_KEY is required")

    # Numeric validation
    [[ ! "$DB_PORT" =~ ^[0-9]+$ ]] && errors+=("DB_PORT must be numeric")
    [[ ! "$RETENTION_DAYS" =~ ^[0-9]+$ ]] && errors+=("RETENTION_DAYS must be numeric")
    [[ ! "$PARALLEL_JOBS" =~ ^[0-9]+$ ]] && errors+=("PARALLEL_JOBS must be numeric")

    # Format validation
    [[ ! "$BACKUP_FORMAT" =~ ^(custom|plain)$ ]] && errors+=("BACKUP_FORMAT must be 'custom' or 'plain'")
    [[ ! "$COMPRESSION" =~ ^(gzip|pigz|lz4|zstd|none)$ ]] && errors+=("COMPRESSION must be gzip, pigz, lz4, zstd, or none")

    # Slack validation
    if [[ "$ENABLE_SLACK" == "true" ]] && [[ -z "$SLACK_WEBHOOK_URL" ]]; then
        errors+=("SLACK_WEBHOOK_URL is required when ENABLE_SLACK=true")
    fi

    # Webhook validation
    if [[ "$ENABLE_WEBHOOK" == "true" ]] && [[ -z "$WEBHOOK_URL" ]]; then
        errors+=("WEBHOOK_URL is required when ENABLE_WEBHOOK=true")
    fi

    if [[ ${#errors[@]} -gt 0 ]]; then
        log_error "Configuration validation failed:"
        printf '%s\n' "${errors[@]}" >&2
        exit 1
    fi
}

check_dependencies() {
    local missing_deps=()

    # Required commands
    local required_commands=(
        "pg_dump"
        "aws"
        "date"
        "du"
        "find"
        "curl"
    )

    for cmd in "${required_commands[@]}"; do
        if ! command -v "$cmd" &> /dev/null; then
            missing_deps+=("$cmd")
        fi
    done

    # Compression tools
    case "$COMPRESSION" in
        gzip) command -v gzip &> /dev/null || missing_deps+=("gzip") ;;
        pigz) command -v pigz &> /dev/null || missing_deps+=("pigz") ;;
        lz4) command -v lz4 &> /dev/null || missing_deps+=("lz4") ;;
        zstd) command -v zstd &> /dev/null || missing_deps+=("zstd") ;;
    esac

    # Email dependencies
    if [[ "$ENABLE_EMAIL" == "true" ]]; then
        if ! command -v mail &> /dev/null && ! command -v sendmail &> /dev/null; then
            missing_deps+=("mail or sendmail")
        fi
    fi

    if [[ ${#missing_deps[@]} -gt 0 ]]; then
        log_error "Missing required dependencies: ${missing_deps[*]}"
        exit 1
    fi
}

# ==============================================================================
# LOGGING FUNCTIONS
# ==============================================================================

setup_logging() {
    # Create log directory if it doesn't exist
    mkdir -p "$LOG_DIR"
    
    # Rotate log files if they exceed max size
    if [[ -f "$LOG_FILE" ]] && [[ $(stat -c%s "$LOG_FILE" 2>/dev/null || echo 0) -gt $MAX_LOG_SIZE ]]; then
        mv "$LOG_FILE" "${LOG_FILE}.old"
    fi

    # Initialize log file
    exec 3>&1 4>&2  # Save stdout and stderr
    exec 1> >(tee -a "$LOG_FILE")
    exec 2> >(tee -a "$LOG_FILE" >&2)
}

log_message() {
    local level="$1"
    shift
    local message="$*"
    local timestamp=$(date '+%Y-%m-%d %H:%M:%S')
    
    echo "[$timestamp] [$level] [PID:$SCRIPT_PID] $message"
}

log_info() {
    log_message "INFO" "$@"
}

log_warn() {
    log_message "WARN" "$@"
}

log_error() {
    log_message "ERROR" "$@"
}

log_success() {
    log_message "SUCCESS" "$@"
}

# ==============================================================================
# NOTIFICATION FUNCTIONS
# ==============================================================================

send_email_notification() {
    local subject="$1"
    local body="$2"
    local priority="${3:-normal}"  # high, normal, low

    if [[ "$ENABLE_EMAIL" != "true" ]]; then
        return 0
    fi

    local priority_header=""
    case "$priority" in
        high) priority_header="X-Priority: 1\nImportance: high" ;;
        low) priority_header="X-Priority: 5\nImportance: low" ;;
        *) priority_header="X-Priority: 3\nImportance: normal" ;;
    esac

    if command -v mail &> /dev/null; then
        echo -e "$body" | mail -s "$subject" -a "From: PostgreSQL Backup <noreply@$(hostname)>" \
                              -a "$priority_header" "$EMAIL_RECIPIENTS"
    elif command -v sendmail &> /dev/null; then
        {
            echo "To: $EMAIL_RECIPIENTS"
            echo "Subject: $subject"
            echo "From: PostgreSQL Backup <noreply@$(hostname)>"
            echo -e "$priority_header"
            echo ""
            echo -e "$body"
        } | sendmail "$EMAIL_RECIPIENTS"
    else
        log_error "No email client available (mail/sendmail)"
        return 1
    fi
}

send_slack_notification() {
    local level="$1"  # INFO, SUCCESS, WARN, ERROR
    local title="$2"
    local message="$3"

    if [[ "$ENABLE_SLACK" != "true" ]]; then
        return 0
    fi

    local color="good"
    local icon=":information_source:"
    
    case "$level" in
        SUCCESS)
            color="good"
            icon=":white_check_mark:"
            ;;
        WARN)
            color="warning"
            icon=":warning:"
            ;;
        ERROR)
            color="danger"
            icon=":x:"
            ;;
        *)
            color="#439FE0"
            icon=":information_source:"
            ;;
    esac

    local payload=$(cat <<EOF
{
    "channel": "$SLACK_CHANNEL",
    "username": "PostgreSQL Backup Bot",
    "icon_emoji": "$icon",
    "attachments": [
        {
            "color": "$color",
            "title": "$title",
            "text": "$message",
            "footer": "Host: $(hostname)",
            "ts": $(date +%s)
        }
    ]
}
EOF
)

    if ! curl -s -X POST -H 'Content-type: application/json' \
         --data "$payload" "$SLACK_WEBHOOK_URL" > /dev/null; then
        log_error "Failed to send Slack notification"
        return 1
    fi
}

send_webhook_notification() {
    local level="$1"
    local title="$2"
    local message="$3"

    if [[ "$ENABLE_WEBHOOK" != "true" ]]; then
        return 0
    fi

    local payload=$(cat <<EOF
{
    "level": "$level",
    "title": "$title",
    "message": "$message",
    "hostname": "$(hostname)",
    "timestamp": "$(date -Iseconds)",
    "script": "$SCRIPT_NAME",
    "database": "$DB_NAME"
}
EOF
)

    if ! curl -s -X POST -H 'Content-Type: application/json' \
         --data "$payload" "$WEBHOOK_URL" > /dev/null; then
        log_error "Failed to send webhook notification"
        return 1
    fi
}

notify_all() {
    local level="$1"
    local title="$2"
    local message="$3"
    local email_priority="${4:-normal}"

    send_email_notification "$title" "$message" "$email_priority"
    send_slack_notification "$level" "$title" "$message"
    send_webhook_notification "$level" "$title" "$message"
}

# ==============================================================================
# UTILITY FUNCTIONS
# ==============================================================================

human_readable_size() {
    local bytes="$1"
    local units=("B" "KB" "MB" "GB" "TB")
    local unit=0
    local size="$bytes"

    while (( size > 1024 && unit < ${#units[@]}-1 )); do
        size=$((size / 1024))
        ((unit++))
    done

    echo "${size}${units[unit]}"
}

cleanup_temp_files() {
    if [[ -d "$BACKUP_DIR" ]]; then
        log_info "Cleaning up temporary files"
        find "$BACKUP_DIR" -name "*.tmp" -type f -delete 2>/dev/null || true
    fi
}

cleanup_on_exit() {
    local exit_code=$?
    
    cleanup_temp_files
    
    # Restore stdout and stderr
    exec 1>&3 2>&4
    exec 3>&- 4>&-

    if [[ $exit_code -ne 0 ]]; then
        notify_all "ERROR" "PostgreSQL Backup Failed" \
                  "Backup process failed with exit code $exit_code. Check logs at $LOG_FILE for details." "high"
    fi
    
    exit $exit_code
}

# ==============================================================================
# DATABASE FUNCTIONS
# ==============================================================================

test_database_connection() {
    log_info "Testing database connection to $DB_HOST:$DB_PORT/$DB_NAME"
    
    local pg_cmd_base="PGPASSWORD='$DB_PASSWORD' psql -h '$DB_HOST' -p '$DB_PORT' -U '$DB_USER'"
    
    if ! eval "$pg_cmd_base -d '$DB_NAME' -c 'SELECT 1;'" &>/dev/null; then
        log_error "Cannot connect to database $DB_NAME"
        notify_all "ERROR" "Database Connection Failed" \
                  "Unable to connect to PostgreSQL database $DB_NAME at $DB_HOST:$DB_PORT" "high"
        return 1
    fi
    
    log_success "Database connection successful"
    return 0
}

get_database_size() {
    local pg_cmd_base="PGPASSWORD='$DB_PASSWORD' psql -h '$DB_HOST' -p '$DB_PORT' -U '$DB_USER'"
    
    eval "$pg_cmd_base -d '$DB_NAME' -t -c \"SELECT pg_size_pretty(pg_database_size('$DB_NAME'));\"" | xargs
}

# ==============================================================================
# BACKUP FUNCTIONS
# ==============================================================================

create_backup() {
    log_info "Starting backup of database '$DB_NAME'"
    
    # Create backup directory
    mkdir -p "$BACKUP_DIR"
    
    local backup_file_base="${DB_NAME}_${TIMESTAMP}"
    local backup_file_ext
    local compression_ext=""
    
    # Set file extension based on format
    case "$BACKUP_FORMAT" in
        custom)
            backup_file_ext="dump"
            ;;
        plain)
            backup_file_ext="sql"
            ;;
    esac
    
    # Set compression extension
    case "$COMPRESSION" in
        gzip) compression_ext=".gz" ;;
        pigz) compression_ext=".gz" ;;
        lz4) compression_ext=".lz4" ;;
        zstd) compression_ext=".zst" ;;
        none) compression_ext="" ;;
    esac
    
    local backup_file_tmp="$BACKUP_DIR/${backup_file_base}.${backup_file_ext}${compression_ext}.tmp"
    local backup_file_final="$BACKUP_DIR/${backup_file_base}.${backup_file_ext}${compression_ext}"
    
    log_info "Creating backup file: $backup_file_final"
    
    # Build pg_dump command
    local pg_dump_cmd="PGPASSWORD='$DB_PASSWORD' pg_dump"
    pg_dump_cmd+=" -h '$DB_HOST' -p '$DB_PORT' -U '$DB_USER' -d '$DB_NAME'"
    pg_dump_cmd+=" --no-password --verbose"
    
    case "$BACKUP_FORMAT" in
        custom)
            pg_dump_cmd+=" -Fc"
            if [[ "$PARALLEL_JOBS" -gt 1 ]]; then
                pg_dump_cmd+=" -j $PARALLEL_JOBS"
            fi
            ;;
        plain)
            pg_dump_cmd+=" -Fp"
            ;;
    esac

    # Execute backup with compression if needed
    local start_time=$(date +%s)
    local backup_success=false

    if [[ "$BACKUP_FORMAT" == "custom" ]]; then
        # Custom format - pg_dump handles compression
        if eval "$pg_dump_cmd -f '$backup_file_tmp'"; then
            backup_success=true
        fi
    else
        # Plain format - pipe through compression
        case "$COMPRESSION" in
            gzip)
                if eval "$pg_dump_cmd | gzip > '$backup_file_tmp'"; then
                    backup_success=true
                fi
                ;;
            pigz)
                if eval "$pg_dump_cmd | pigz > '$backup_file_tmp'"; then
                    backup_success=true
                fi
                ;;
            lz4)
                if eval "$pg_dump_cmd | lz4 > '$backup_file_tmp'"; then
                    backup_success=true
                fi
                ;;
            zstd)
                if eval "$pg_dump_cmd | zstd > '$backup_file_tmp'"; then
                    backup_success=true
                fi
                ;;
            none)
                if eval "$pg_dump_cmd > '$backup_file_tmp'"; then
                    backup_success=true
                fi
                ;;
        esac
    fi

    local end_time=$(date +%s)
    local duration=$((end_time - start_time))

    if [[ "$backup_success" == true ]]; then
        mv "$backup_file_tmp" "$backup_file_final"
        local backup_size=$(stat -c%s "$backup_file_final")
        local backup_size_hr=$(human_readable_size "$backup_size")
        
        log_success "Backup completed successfully"
        log_info "Backup size: $backup_size_hr"
        log_info "Backup duration: ${duration}s"
        
        echo "$backup_file_final"
        return 0
    else
        log_error "Backup failed"
        [[ -f "$backup_file_tmp" ]] && rm -f "$backup_file_tmp"
        return 1
    fi
}

# ==============================================================================
# S3 FUNCTIONS
# ==============================================================================

configure_aws_cli() {
    log_info "Configuring AWS CLI"
    
    export AWS_ACCESS_KEY_ID="$AWS_ACCESS_KEY_ID"
    export AWS_SECRET_ACCESS_KEY="$AWS_SECRET_ACCESS_KEY"
    export AWS_DEFAULT_REGION="$S3_REGION"
    
    # Test AWS configuration
    if ! aws sts get-caller-identity &>/dev/null; then
        log_error "AWS CLI configuration failed"
        return 1
    fi
    
    log_success "AWS CLI configured successfully"
    return 0
}

upload_to_s3() {
    local backup_file="$1"
    local s3_key="$S3_PREFIX/$(basename "$backup_file")"
    local s3_uri="s3://$S3_BUCKET/$s3_key"
    
    log_info "Uploading backup to S3: $s3_uri"
    
    local start_time=$(date +%s)
    
    if aws s3 cp "$backup_file" "$s3_uri" \
       --storage-class STANDARD_IA \
       --metadata "database=$DB_NAME,timestamp=$TIMESTAMP,hostname=$(hostname)"; then
        
        local end_time=$(date +%s)
        local upload_duration=$((end_time - start_time))
        
        log_success "Upload completed successfully in ${upload_duration}s"
        log_info "S3 location: $s3_uri"
        
        return 0
    else
        log_error "Upload to S3 failed"
        return 1
    fi
}

cleanup_old_backups_s3() {
    log_info "Cleaning up old backups in S3 (retention: $RETENTION_DAYS days)"
    
    local cutoff_date=$(date -d "$RETENTION_DAYS days ago" '+%Y-%m-%d')
    local deleted_count=0
    
    # List and delete old backups
    while IFS=$'\t' read -r key last_modified size; do
        local file_date=$(echo "$last_modified" | cut -d'T' -f1)
        
        if [[ "$file_date" < "$cutoff_date" ]]; then
            local s3_uri="s3://$S3_BUCKET/$key"
            log_info "Deleting old backup: $s3_uri"
            
            if aws s3 rm "$s3_uri"; then
                ((deleted_count++))
            else
                log_warn "Failed to delete: $s3_uri"
            fi
        fi
    done < <(aws s3api list-objects --bucket "$S3_BUCKET" --prefix "$S3_PREFIX/" \
             --query 'Contents[?contains(Key, `'"$DB_NAME"'`)].[Key,LastModified,Size]' \
             --output text 2>/dev/null || true)
    
    log_info "Deleted $deleted_count old backup(s) from S3"
}

cleanup_local_backups() {
    log_info "Cleaning up local backup files older than 1 day"
    
    local deleted_count=0
    
    if [[ -d "$BACKUP_DIR" ]]; then
        while IFS= read -r -d '' file; do
            log_info "Deleting local backup: $file"
            rm -f "$file"
            ((deleted_count++))
        done < <(find "$BACKUP_DIR" -name "${DB_NAME}_*.dump*" -o -name "${DB_NAME}_*.sql*" \
                 -type f -mtime +1 -print0 2>/dev/null)
    fi
    
    log_info "Deleted $deleted_count local backup(s)"
}

# ==============================================================================
# MAIN EXECUTION
# ==============================================================================

main() {
    local start_time=$(date +%s)
    
    log_info "===== PostgreSQL Backup Script Started ====="
    log_info "Database: $DB_NAME"
    log_info "Host: $DB_HOST:$DB_PORT"
    log_info "S3 Bucket: $S3_BUCKET"
    log_info "Retention: $RETENTION_DAYS days"
    log_info "Format: $BACKUP_FORMAT"
    log_info "Compression: $COMPRESSION"
    
    # Validate configuration
    validate_config
    
    # Check dependencies
    check_dependencies
    
    # Test database connection
    if ! test_database_connection; then
        exit 1
    fi
    
    # Get database size for logging
    local db_size=$(get_database_size)
    log_info "Database size: $db_size"
    
    # Configure AWS CLI
    if ! configure_aws_cli; then
        notify_all "ERROR" "AWS Configuration Failed" \
                  "Failed to configure AWS CLI for S3 backup" "high"
        exit 1
    fi
    
    # Create backup
    local backup_file
    if backup_file=$(create_backup); then
        log_success "Local backup created: $backup_file"
    else
        notify_all "ERROR" "Backup Creation Failed" \
                  "Failed to create PostgreSQL backup for database $DB_NAME" "high"
        exit 1
    fi
    
    # Upload to S3
    if upload_to_s3 "$backup_file"; then
        log_success "Backup uploaded to S3 successfully"
    else
        notify_all "ERROR" "S3 Upload Failed" \
                  "Failed to upload backup to S3. Local backup preserved at: $backup_file" "high"
        exit 1
    fi
    
    # Cleanup old backups
    cleanup_old_backups_s3
    cleanup_local_backups
    
    local end_time=$(date +%s)
    local total_duration=$((end_time - start_time))
    
    log_success "===== Backup Process Completed Successfully ====="
    log_info "Total duration: ${total_duration}s"
    
    # Send success notification
    local backup_info="Database: $DB_NAME\nSize: $db_size\nDuration: ${total_duration}s\nLocation: s3://$S3_BUCKET/$S3_PREFIX/$(basename "$backup_file")"
    notify_all "SUCCESS" "PostgreSQL Backup Completed" "$backup_info"
}

# ==============================================================================
# SCRIPT INITIALIZATION
# ==============================================================================

# Set up signal handlers
trap cleanup_on_exit EXIT INT TERM

# Set up logging
setup_logging

# Check if running as root (optional warning)
if [[ $EUID -eq 0 ]]; then
    log_warn "Running as root user"
fi

# Validate required environment
if [[ "${BASH_VERSINFO[0]}" -lt 4 ]]; then
    log_error "Bash 4.0 or higher required"
    exit 1
fi

# Run main function
main "$@"
```

This comprehensive PostgreSQL backup script includes:

## Key Features:

1. **Configuration Management**: 
Uses environment variables for easy configuration of database connections, S3 settings, and notification preferences


2. **Comprehensive Logging**: 
Structured logging with multiple levels, automatic log rotation, and detailed backup metrics


3. **Multiple Backup Formats**: 
Supports both custom format (-Fc) for compressed binary files and plain SQL format with various compression options


4. **S3 Storage**: 
Uses AWS S3 with configurable storage classes and metadata tagging for organized backup management


5. **Backup Rotation**: 
Automatically removes old backups based on configurable retention period


6. **Error Handling**: Robust error checking with detailed exit codes and cleanup procedures

7. **Multi-Channel Notifications**:
   - **Email**: Traditional SMTP notifications
   - **Slack**: 
Webhook-based notifications with color-coded messages for different severity levels

   - **Custom Webhooks**: JSON payload delivery to custom endpoints

8. **Performance Optimization**: 
Support for parallel jobs in custom format backups and various compression algorithms like pigz for better performance


9. **Security Best Practices**: 
Uses environment variables for credentials and supports minimal IAM permissions


## Usage Example:

```bash
# Set environment variables
export DB_NAME="myapp_production"
export DB_HOST="localhost"
export DB_USER="backup_user"
export DB_PASSWORD="secure_password"
export S3_BUCKET="my-backup-bucket"
export AWS_ACCESS_KEY_ID="AKIA..."
export AWS_SECRET_ACCESS_KEY="xxx..."
export SLACK_WEBHOOK_URL="https://hooks.slack.com/services/..."
export ENABLE_SLACK="true"

# Run the backup
./postgresql-backup.sh
```

The script can be scheduled via cron for automated daily backups and provides comprehensive monitoring and alerting for production database environments.
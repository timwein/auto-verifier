```bash
#!/bin/bash

# ==============================================================================
# PostgreSQL Backup Script with S3 Upload, Rotation, and Notifications
# ==============================================================================
# Author: Database Administrator
# Version: 2.0
# Description: Automated PostgreSQL backup with AWS S3 storage, rotation,
#              comprehensive logging, WAL archiving, and multi-channel notifications
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
readonly DB_SSL_MODE="${DB_SSL_MODE:-require}"
readonly DB_CONNECTION_TIMEOUT="${DB_CONNECTION_TIMEOUT:-30}"

# AWS S3 Configuration
readonly S3_BUCKET="${S3_BUCKET:-}"
readonly S3_PREFIX="${S3_PREFIX:-postgresql-backups}"
readonly S3_WAL_PREFIX="${S3_WAL_PREFIX:-wal}"
readonly S3_REGION="${S3_REGION:-us-east-1}"

# Backup Configuration
readonly BACKUP_DIR="${BACKUP_DIR:-/tmp/pg_backups}"
readonly RETENTION_DAYS="${RETENTION_DAYS:-7}"
readonly WEEKLY_RETENTION="${WEEKLY_RETENTION:-28}"
readonly MONTHLY_RETENTION="${MONTHLY_RETENTION:-365}"
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

readonly ENABLE_PAGERDUTY="${ENABLE_PAGERDUTY:-false}"
readonly PAGERDUTY_SERVICE_KEY="${PAGERDUTY_SERVICE_KEY:-}"

# Disaster Recovery Configuration
readonly DR_RPO_HOURS="${DR_RPO_HOURS:-1}"
readonly DR_RTO_HOURS="${DR_RTO_HOURS:-4}"
readonly TEST_RECOVERY_SCHEDULE="${TEST_RECOVERY_SCHEDULE:-monthly}"

# Compliance Configuration
readonly COMPLIANCE_ENABLED="${COMPLIANCE_ENABLED:-false}"
readonly LEGAL_HOLD_ENABLED="${LEGAL_HOLD_ENABLED:-false}"
readonly COMPLIANCE_RETENTION_YEARS="${COMPLIANCE_RETENTION_YEARS:-7}"

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
        "pg_restore"
        "aws"
        "date"
        "du"
        "find"
        "curl"
        "sha256sum"
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

check_disk_space() {
    local backup_dir_space_usage
    backup_dir_space_usage=$(df "$BACKUP_DIR" | awk 'NR==2{gsub(/%/,"",$5); print $5}')
    
    if [[ $backup_dir_space_usage -gt 90 ]]; then
        log_error "Insufficient disk space: ${backup_dir_space_usage}% used in backup directory"
        return 1
    fi
    
    log_info "Disk space check passed: ${backup_dir_space_usage}% used"
    return 0
}

setup_pgpass() {
    if [[ -n "$DB_PASSWORD" ]] && [[ ! -f "$HOME/.pgpass" ]]; then
        local pgpass_file="$HOME/.pgpass"
        echo "$DB_HOST:$DB_PORT:$DB_NAME:$DB_USER:$DB_PASSWORD" > "$pgpass_file"
        chmod 600 "$pgpass_file"
        log_info "Created .pgpass file with secure permissions"
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

log_json() {
    local level="$1"
    local component="${2:-backup}"
    local message="$3"
    local extra_fields="${4:-}"
    
    local timestamp=$(date -Iseconds)
    local json_log="{\"timestamp\":\"$timestamp\",\"level\":\"$level\",\"pid\":$SCRIPT_PID,\"component\":\"$component\",\"message\":\"$message\""
    
    if [[ -n "$extra_fields" ]]; then
        json_log+=",${extra_fields}"
    fi
    
    json_log+="}"
    echo "$json_log"
}

log_message() {
    local level="$1"
    shift
    local message="$*"
    local timestamp=$(date '+%Y-%m-%d %H:%M:%S')
    
    # Structured JSON logging
    log_json "$level" "backup" "$message"
    
    # Human-readable logging for console
    echo "[$timestamp] [$level] [PID:$SCRIPT_PID] $message" >&2
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

log_metrics() {
    local metrics="$1"
    log_json "INFO" "metrics" "Backup metrics collected" "$metrics"
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

send_pagerduty_notification() {
    local level="$1"
    local title="$2"
    local message="$3"

    if [[ "$ENABLE_PAGERDUTY" != "true" ]] || [[ "$level" != "ERROR" ]]; then
        return 0
    fi

    local payload=$(cat <<EOF
{
    "payload": {
        "summary": "$title",
        "source": "$(hostname)",
        "severity": "critical",
        "component": "postgresql-backup",
        "custom_details": {
            "message": "$message",
            "database": "$DB_NAME",
            "timestamp": "$(date -Iseconds)"
        }
    },
    "routing_key": "$PAGERDUTY_SERVICE_KEY",
    "event_action": "trigger"
}
EOF
)

    if ! curl -s -X POST -H 'Content-Type: application/json' \
         --data "$payload" "https://events.pagerduty.com/v2/enqueue" > /dev/null; then
        log_error "Failed to send PagerDuty notification"
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
    send_pagerduty_notification "$level" "$title" "$message"
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
    log_info "Testing database connection to $DB_HOST:$DB_PORT/$DB_NAME with SSL mode: $DB_SSL_MODE"
    
    local pg_cmd_base="psql -h '$DB_HOST' -p '$DB_PORT' -U '$DB_USER' --ssl-mode='$DB_SSL_MODE'"
    local timeout_cmd=""
    
    if [[ "$DB_CONNECTION_TIMEOUT" -gt 0 ]]; then
        timeout_cmd="timeout $DB_CONNECTION_TIMEOUT"
    fi
    
    local retry_count=0
    local max_retries=3
    
    while [[ $retry_count -lt $max_retries ]]; do
        if eval "$timeout_cmd $pg_cmd_base -d '$DB_NAME' -c 'SELECT 1;'" &>/dev/null; then
            log_success "Database connection successful"
            return 0
        fi
        
        local pg_exit_code=$?
        retry_count=$((retry_count + 1))
        
        case $pg_exit_code in
            1) 
                log_error "Database connection failed: Authentication error"
                ;;
            2) 
                log_error "Database connection failed: Connection error"
                ;;
            40001|40P01)
                log_warn "Serialization failure (code: $pg_exit_code), retrying... (attempt $retry_count/$max_retries)"
                if [[ $retry_count -lt $max_retries ]]; then
                    sleep $((2**retry_count))
                    continue
                fi
                ;;
            124)
                log_error "Database connection timed out after ${DB_CONNECTION_TIMEOUT}s"
                ;;
            *)
                log_error "Database connection failed with unknown error code: $pg_exit_code"
                ;;
        esac
        
        if [[ $retry_count -ge $max_retries ]]; then
            notify_all "ERROR" "Database Connection Failed" \
                      "Unable to connect to PostgreSQL database $DB_NAME at $DB_HOST:$DB_PORT after $max_retries attempts" "high"
            return 1
        fi
        
        sleep $((retry_count * 2))
    done
}

get_database_size() {
    local pg_cmd_base="psql -h '$DB_HOST' -p '$DB_PORT' -U '$DB_USER' --ssl-mode='$DB_SSL_MODE'"
    
    eval "$pg_cmd_base -d '$DB_NAME' -t -c \"SELECT pg_size_pretty(pg_database_size('$DB_NAME'));\"" | xargs
}

# ==============================================================================
# BACKUP INTEGRITY FUNCTIONS
# ==============================================================================

verify_backup_integrity() {
    local backup_file="$1"
    local verification_log="/tmp/backup_verification_${TIMESTAMP}.log"
    
    log_info "Performing backup integrity verification"
    
    # Create checksum
    local checksum_file="${backup_file}.sha256"
    sha256sum "$backup_file" > "$checksum_file"
    log_info "Created backup checksum: $(cat "$checksum_file")"
    
    # Verify backup format and structure
    case "$BACKUP_FORMAT" in
        custom)
            # Test pg_restore --list functionality
            if pg_restore --list "$backup_file" > "$verification_log" 2>&1; then
                local table_count=$(grep "TABLE DATA" "$verification_log" | wc -l)
                log_success "Backup format validation passed: $table_count tables found"
            else
                log_error "Backup format validation failed: pg_restore --list failed"
                cat "$verification_log"
                return 1
            fi
            ;;
        plain)
            # Check SQL file integrity
            if tail -1 "$backup_file" | grep -q "PostgreSQL database dump complete"; then
                log_success "SQL backup format validation passed"
            else
                log_error "SQL backup appears truncated or incomplete"
                return 1
            fi
            ;;
    esac
    
    # Verify checksum
    if sha256sum -c "$checksum_file" &>/dev/null; then
        log_success "Backup checksum verification passed"
    else
        log_error "Backup checksum verification failed"
        return 1
    fi
    
    # Test restoration (dry run for small databases)
    local db_size_bytes
    db_size_bytes=$(eval "psql -h '$DB_HOST' -p '$DB_PORT' -U '$DB_USER' -d '$DB_NAME' --ssl-mode='$DB_SSL_MODE' -t -c \"SELECT pg_database_size('$DB_NAME');\"" | xargs)
    
    # Only test restore for databases smaller than 1GB
    if [[ $db_size_bytes -lt 1073741824 ]]; then
        log_info "Performing test restoration for small database"
        if test_restore_backup "$backup_file"; then
            log_success "Test restoration completed successfully"
        else
            log_error "Test restoration failed"
            return 1
        fi
    else
        log_info "Skipping test restoration for large database (${db_size_bytes} bytes)"
    fi
    
    rm -f "$verification_log"
    return 0
}

test_restore_backup() {
    local backup_file="$1"
    local test_db="test_restore_$$"
    
    # Create temporary test database
    if ! eval "createdb -h '$DB_HOST' -p '$DB_PORT' -U '$DB_USER' '$test_db'" &>/dev/null; then
        log_error "Failed to create test database"
        return 1
    fi
    
    # Attempt restoration
    local restore_success=false
    case "$BACKUP_FORMAT" in
        custom)
            if pg_restore -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" --ssl-mode="$DB_SSL_MODE" \
               -d "$test_db" -j "$PARALLEL_JOBS" "$backup_file" &>/dev/null; then
                restore_success=true
            fi
            ;;
        plain)
            if eval "psql -h '$DB_HOST' -p '$DB_PORT' -U '$DB_USER' --ssl-mode='$DB_SSL_MODE' \
                    -d '$test_db' < '$backup_file'" &>/dev/null; then
                restore_success=true
            fi
            ;;
    esac
    
    # Cleanup test database
    eval "dropdb -h '$DB_HOST' -p '$DB_PORT' -U '$DB_USER' '$test_db'" &>/dev/null || true
    
    [[ "$restore_success" == "true" ]]
}

# ==============================================================================
# AWS FUNCTIONS
# ==============================================================================

configure_aws_cli() {
    log_info "Configuring AWS CLI with IAM role authentication"
    
    # Use IAM role instead of hardcoded credentials
    export AWS_DEFAULT_REGION="$S3_REGION"
    
    # Test AWS configuration using IAM role
    if aws sts get-caller-identity &>/dev/null; then
        log_success "AWS CLI configured successfully with IAM role"
        local identity
        identity=$(aws sts get-caller-identity --query 'Arn' --output text)
        log_info "Using AWS identity: $identity"
    else
        log_error "AWS CLI configuration failed - ensure IAM role has proper permissions"
        return 1
    fi
    
    return 0
}

upload_to_s3() {
    local backup_file="$1"
    local s3_key="$S3_PREFIX/$(basename "$backup_file")"
    local s3_uri="s3://$S3_BUCKET/$s3_key"
    
    log_info "Uploading backup to S3: $s3_uri"
    
    local start_time=$(date +%s)
    
    # Upload with encryption and metadata
    if aws s3 cp "$backup_file" "$s3_uri" \
       --storage-class STANDARD_IA \
       --server-side-encryption AES256 \
       --metadata "database=$DB_NAME,timestamp=$TIMESTAMP,hostname=$(hostname)" \
       --only-show-errors; then
        
        local end_time=$(date +%s)
        local upload_duration=$((end_time - start_time))
        
        log_success "Upload completed successfully in ${upload_duration}s"
        log_info "S3 location: $s3_uri"
        
        # Upload checksum file
        local checksum_file="${backup_file}.sha256"
        if [[ -f "$checksum_file" ]]; then
            aws s3 cp "$checksum_file" "${s3_uri}.sha256" \
                --server-side-encryption AES256 \
                --only-show-errors
        fi
        
        return 0
    else
        log_error "Upload to S3 failed"
        return 1
    fi
}

create_s3_lifecycle_policy() {
    local policy_file="/tmp/s3_lifecycle_policy.json"
    
    cat > "$policy_file" <<EOF
{
    "Rules": [
        {
            "ID": "PostgreSQL-Backup-Lifecycle",
            "Status": "Enabled",
            "Filter": {
                "Prefix": "$S3_PREFIX/"
            },
            "Transitions": [
                {
                    "Days": 7,
                    "StorageClass": "GLACIER"
                },
                {
                    "Days": 90,
                    "StorageClass": "DEEP_ARCHIVE"
                }
            ]
        },
        {
            "ID": "WAL-Archive-Lifecycle", 
            "Status": "Enabled",
            "Filter": {
                "Prefix": "$S3_WAL_PREFIX/"
            },
            "Transitions": [
                {
                    "Days": 30,
                    "StorageClass": "GLACIER"
                }
            ],
            "Expiration": {
                "Days": 2555
            }
        }
    ]
}
EOF

    if [[ "$COMPLIANCE_ENABLED" == "true" ]]; then
        cat > "$policy_file" <<EOF
{
    "Rules": [
        {
            "ID": "PostgreSQL-Backup-Compliance",
            "Status": "Enabled", 
            "Filter": {
                "Prefix": "$S3_PREFIX/"
            },
            "Transitions": [
                {
                    "Days": 7,
                    "StorageClass": "GLACIER"
                },
                {
                    "Days": 90,
                    "StorageClass": "DEEP_ARCHIVE"
                }
            ],
            "Expiration": {
                "Days": $((COMPLIANCE_RETENTION_YEARS * 365))
            }
        }
    ]
}
EOF
    fi

    if aws s3api put-bucket-lifecycle-configuration \
       --bucket "$S3_BUCKET" \
       --lifecycle-configuration file://"$policy_file" &>/dev/null; then
        log_info "S3 lifecycle policy configured successfully"
    else
        log_warn "Failed to configure S3 lifecycle policy"
    fi
    
    rm -f "$policy_file"
}

cleanup_old_backups_s3() {
    log_info "Cleaning up old backups in S3 using tiered retention strategy"
    
    local today=$(date '+%Y-%m-%d')
    local daily_cutoff=$(date -d "$RETENTION_DAYS days ago" '+%Y-%m-%d')
    local weekly_cutoff=$(date -d "$WEEKLY_RETENTION days ago" '+%Y-%m-%d')
    local monthly_cutoff=$(date -d "$MONTHLY_RETENTION days ago" '+%Y-%m-%d')
    local deleted_count=0
    
    # Implement tiered retention: daily/weekly/monthly
    while IFS=$'\t' read -r key last_modified size; do
        local file_date=$(echo "$last_modified" | cut -d'T' -f1)
        local should_delete=false
        
        # Determine if file should be deleted based on tiered retention
        if [[ "$file_date" < "$daily_cutoff" ]]; then
            # Check if it's a weekly backup (every 7th day)
            local day_of_year=$(date -d "$file_date" '+%j')
            if (( day_of_year % 7 != 0 )) && [[ "$file_date" < "$weekly_cutoff" ]]; then
                should_delete=true
            elif (( day_of_year % 7 == 0 )) && (( day_of_year % 30 != 0 )) && [[ "$file_date" < "$monthly_cutoff" ]]; then
                should_delete=true
            fi
        fi
        
        # Apply legal hold protection
        if [[ "$should_delete" == "true" ]] && [[ "$LEGAL_HOLD_ENABLED" == "true" ]]; then
            # Check for legal hold tag (simplified check)
            local tags
            tags=$(aws s3api get-object-tagging --bucket "$S3_BUCKET" --key "$key" --query 'TagSet[?Key==`LegalHold`].Value' --output text 2>/dev/null || echo "")
            if [[ "$tags" == "true" ]]; then
                log_info "Skipping deletion of $key due to legal hold"
                should_delete=false
            fi
        fi
        
        if [[ "$should_delete" == "true" ]]; then
            local s3_uri="s3://$S3_BUCKET/$key"
            log_info "Deleting old backup: $s3_uri"
            
            if aws s3 rm "$s3_uri" --only-show-errors; then
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

setup_wal_archiving() {
    log_info "WAL Archiving Configuration Instructions:"
    log_info "Add the following to postgresql.conf:"
    log_info "wal_level = replica"
    log_info "archive_mode = on"
    log_info "archive_command = 'aws s3 cp %p s3://$S3_BUCKET/$S3_WAL_PREFIX/%f --server-side-encryption AES256 --only-show-errors'"
    log_info "archive_timeout = 300  # 5 minutes"
    log_info ""
    log_info "For Point-in-Time Recovery (PITR):"
    log_info "1. Restore base backup to target directory"
    log_info "2. Set recovery_target_time in recovery.conf"
    log_info "3. Configure restore_command = 'aws s3 cp s3://$S3_BUCKET/$S3_WAL_PREFIX/%f %p --only-show-errors'"
    log_info "4. Start PostgreSQL to replay WAL files"
    log_info ""
    log_info "Recovery objectives:"
    log_info "RPO (Recovery Point Objective): $DR_RPO_HOURS hour(s) maximum data loss"
    log_info "RTO (Recovery Time Objective): $DR_RTO_HOURS hour(s) maximum downtime"
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
# BACKUP FUNCTIONS
# ==============================================================================

create_backup() {
    log_info "Starting backup of database '$DB_NAME'"
    
    # Pre-backup checks
    if ! check_disk_space; then
        return 1
    fi
    
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
    
    # Build pg_dump command with enhanced security and consistency
    local pg_dump_cmd="pg_dump -h '$DB_HOST' -p '$DB_PORT' -U '$DB_USER' -d '$DB_NAME'"
    pg_dump_cmd+=" --ssl-mode='$DB_SSL_MODE' --no-password --verbose"
    pg_dump_cmd+=" --serializable-deferrable --no-privileges --no-owner"
    
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

    # Execute backup with retry logic for serialization conflicts
    local start_time=$(date +%s)
    local backup_success=false
    local retry_count=0
    local max_retries=3

    while [[ $retry_count -lt $max_retries ]] && [[ "$backup_success" != "true" ]]; do
        if [[ "$BACKUP_FORMAT" == "custom" ]] && [[ "$compression_ext" == "" ]]; then
            # Custom format without additional compression
            if eval "$pg_dump_cmd -f '$backup_file_tmp'"; then
                backup_success=true
            fi
        else
            # Plain format or custom with additional compression
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

        if [[ "$backup_success" != "true" ]]; then
            local pg_exit_code=$?
            
            # Handle PostgreSQL-specific errors with retry logic
            case $pg_exit_code in
                40001|40)  # Serialization failure codes
                    retry_count=$((retry_count + 1))
                    if [[ $retry_count -lt $max_retries ]]; then
                        local backoff_time=$((2**retry_count))
                        log_warn "Serialization failure, retrying in ${backoff_time}s (attempt $retry_count/$max_retries)"
                        sleep $backoff_time
                        continue
                    else
                        log_error "Backup failed after $max_retries serialization retry attempts"
                        break
                    fi
                    ;;
                *)
                    log_error "Backup failed with PostgreSQL error code: $pg_exit_code"
                    break
                    ;;
            esac
        fi
    done

    local end_time=$(date +%s)
    local duration=$((end_time - start_time))

    if [[ "$backup_success" == "true" ]]; then
        mv "$backup_file_tmp" "$backup_file_final"
        local backup_size=$(stat -c%s "$backup_file_final")
        local backup_size_hr=$(human_readable_size "$backup_size")
        
        log_success "Backup completed successfully"
        log_info "Backup size: $backup_size_hr"
        log_info "Backup duration: ${duration}s"
        
        # Log structured metrics
        local metrics="\"duration\":$duration,\"size\":$backup_size,\"success\":true,\"format\":\"$BACKUP_FORMAT\",\"compression\":\"$COMPRESSION\""
        log_metrics "$metrics"
        
        # Verify backup integrity
        if verify_backup_integrity "$backup_file_final"; then
            log_success "Backup integrity verification passed"
            echo "$backup_file_final"
            return 0
        else
            log_error "Backup integrity verification failed"
            return 1
        fi
    else
        log_error "Backup failed"
        [[ -f "$backup_file_tmp" ]] && rm -f "$backup_file_tmp"
        
        # Log failed metrics
        local metrics="\"duration\":$duration,\"size\":0,\"success\":false,\"error\":\"backup_creation_failed\""
        log_metrics "$metrics"
        return 1
    fi
}

# ==============================================================================
# DISASTER RECOVERY FUNCTIONS
# ==============================================================================

create_recovery_scripts() {
    local recovery_script_dir="/usr/local/bin/postgresql-recovery"
    mkdir -p "$recovery_script_dir"
    
    # Automated recovery script
    cat > "$recovery_script_dir/automated_recovery.sh" <<'EOF'
#!/bin/bash
# Automated PostgreSQL Recovery Script
# Usage: ./automated_recovery.sh <backup_s3_path> <target_directory> [recovery_target_time]

set -euo pipefail

BACKUP_S3_PATH="$1"
TARGET_DIR="$2"
RECOVERY_TARGET_TIME="${3:-latest}"

echo "Starting automated PostgreSQL recovery..."
echo "Source: $BACKUP_S3_PATH"
echo "Target: $TARGET_DIR"

# Download backup from S3
aws s3 cp "$BACKUP_S3_PATH" ./backup.dump --only-show-errors

# Extract if compressed
if [[ "$BACKUP_S3_PATH" == *.gz ]]; then
    gunzip backup.dump.gz
    mv backup.dump.gz backup.dump
fi

# Create target directory
mkdir -p "$TARGET_DIR"

# Restore backup
pg_restore -d postgres --create backup.dump

echo "Recovery completed successfully"
EOF

    chmod +x "$recovery_script_dir/automated_recovery.sh"
    
    log_info "Created automated recovery scripts in $recovery_script_dir"
}

document_disaster_recovery() {
    local dr_doc="/usr/local/share/postgresql-backup-dr.md"
    
    cat > "$dr_doc" <<EOF
# PostgreSQL Disaster Recovery Procedures

## Recovery Objectives
- **RPO (Recovery Point Objective)**: $DR_RPO_HOURS hour(s) maximum data loss
- **RTO (Recovery Time Objective)**: $DR_RTO_HOURS hour(s) maximum downtime

## Emergency Contacts
- Database Team: dba@company.com
- Infrastructure Team: infrastructure@company.com  
- Emergency Escalation: on-call@company.com

## Recovery Procedures

### 1. Point-in-Time Recovery (PITR)
\`\`\`bash
# 1. Stop PostgreSQL service
systemctl stop postgresql

# 2. Download base backup
aws s3 cp s3://$S3_BUCKET/$S3_PREFIX/latest_backup.dump /var/lib/postgresql/

# 3. Restore base backup
pg_restore -d $DB_NAME /var/lib/postgresql/latest_backup.dump

# 4. Configure recovery.conf
cat > /var/lib/postgresql/data/recovery.conf << EOL
restore_command = 'aws s3 cp s3://$S3_BUCKET/$S3_WAL_PREFIX/%f %p'
recovery_target_time = 'YYYY-MM-DD HH:MM:SS'
recovery_target_action = 'promote'
EOL

# 5. Start PostgreSQL
systemctl start postgresql
\`\`\`

### 2. Full Restore from Backup
\`\`\`bash
# Use automated recovery script
/usr/local/bin/postgresql-recovery/automated_recovery.sh \\
    s3://$S3_BUCKET/$S3_PREFIX/backup_file.dump \\
    /var/lib/postgresql/data
\`\`\`

### 3. Testing Schedule
- **Monthly**: Full PITR test on test environment
- **Quarterly**: Cross-region restore test
- **Annually**: Complete DR exercise with business users

## Decision Matrix
| Scenario | Action | RTO Target | RPO Impact |
|----------|--------|------------|------------|
| Corruption < 1 hour | PITR | 30 min | < 5 min |
| Hardware failure | Full restore | 2 hours | < 1 hour |
| Region outage | Cross-region restore | 4 hours | < 1 hour |

## Escalation Procedures
1. **Level 1**: Database team attempts recovery
2. **Level 2**: Infrastructure team for hardware/network issues  
3. **Level 3**: Vendor support engagement
4. **Level 4**: Executive notification for business impact

Generated: $(date)
Database: $DB_NAME
Script Version: 2.0
EOF

    log_info "Created disaster recovery documentation: $dr_doc"
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
    log_info "Retention: Daily($RETENTION_DAYS), Weekly($WEEKLY_RETENTION), Monthly($MONTHLY_RETENTION) days"
    log_info "Format: $BACKUP_FORMAT"
    log_info "Compression: $COMPRESSION"
    log_info "SSL Mode: $DB_SSL_MODE"
    
    # Validate configuration
    validate_config
    
    # Check dependencies
    check_dependencies
    
    # Setup secure authentication
    setup_pgpass
    
    # Test database connection
    if ! test_database_connection; then
        exit 1
    fi
    
    # Get database size for logging
    local db_size=$(get_database_size)
    log_info "Database size: $db_size"
    
    # Configure AWS CLI with IAM role
    if ! configure_aws_cli; then
        notify_all "ERROR" "AWS Configuration Failed" \
                  "Failed to configure AWS CLI with IAM role for S3 backup" "high"
        exit 1
    fi
    
    # Create S3 lifecycle policy for cost optimization
    create_s3_lifecycle_policy
    
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
    
    # Generate WAL archiving instructions
    setup_wal_archiving
    
    # Create disaster recovery documentation
    document_disaster_recovery
    create_recovery_scripts
    
    local end_time=$(date +%s)
    local total_duration=$((end_time - start_time))
    
    log_success "===== Backup Process Completed Successfully ====="
    log_info "Total duration: ${total_duration}s"
    
    # Send success notification
    local backup_info="Database: $DB_NAME\nSize: $db_size\nDuration: ${total_duration}s\nLocation: s3://$S3_BUCKET/$S3_PREFIX/$(basename "$backup_file")\n\nRecovery Objectives:\nRPO: $DR_RPO_HOURS hour(s)\nRTO: $DR_RTO_HOURS hour(s)\n\nNext DR Test: $TEST_RECOVERY_SCHEDULE"
    notify_all "SUCCESS" "PostgreSQL Backup Completed" "$backup_info"
    
    # Log final metrics
    local final_metrics="\"total_duration\":$total_duration,\"database_size_pretty\":\"$db_size\",\"backup_file\":\"$(basename "$backup_file")\""
    log_metrics "$final_metrics"
}

# ==============================================================================
# SCRIPT INITIALIZATION
# ==============================================================================

# Set up signal handlers
trap cleanup_on_exit EXIT INT TERM

# Set up logging
setup_logging

# Check if running as root (optional warning)
if [[ $
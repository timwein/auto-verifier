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
readonly PARALLEL_JOBS="${PARALLEL_JOBS:-$(nproc)}"
readonly BACKUP_FORMAT="${BACKUP_FORMAT:-custom}"  # custom or plain
readonly BACKUP_TYPE="${BACKUP_TYPE:-full}"  # full, differential, incremental

# pgBackRest Configuration
readonly PGBACKREST_STANZA="${PGBACKREST_STANZA:-$DB_NAME}"
readonly PGBACKREST_CONFIG_FILE="${PGBACKREST_CONFIG_FILE:-/etc/pgbackrest/pgbackrest.conf}"

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
    [[ ! "$BACKUP_TYPE" =~ ^(full|differential|incremental)$ ]] && errors+=("BACKUP_TYPE must be 'full', 'differential', or 'incremental'")
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

    # Required commands - prioritize pgBackRest over pg_dump
    local required_commands=(
        "pgbackrest"
        "aws"
        "date"
        "du"
        "find"
        "curl"
        "sha256sum"
        "psql"
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
    # Use environment variable for authentication instead of hardcoded password
    if [[ -n "${PGPASSWORD:-}" ]] && [[ ! -f "$HOME/.pgpass" ]]; then
        local pgpass_file="$HOME/.pgpass"
        echo "$DB_HOST:$DB_PORT:$DB_NAME:$DB_USER:$PGPASSWORD" > "$pgpass_file"
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
    
    local pg_cmd_base="psql -h '$DB_HOST' -p '$DB_PORT' -U '$DB_USER' --ssl-mode='$DB_SSL_MODE' --no-password"
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
            55P03)
                log_warn "Lock timeout (code: $pg_exit_code), retrying... (attempt $retry_count/$max_retries)"
                if [[ $retry_count -lt $max_retries ]]; then
                    sleep $((retry_count * 2))
                    continue
                fi
                ;;
            53100)
                log_error "Database disk full error (code: $pg_exit_code)"
                ;;
            53200)
                log_error "Database out of memory error (code: $pg_exit_code)"
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
        
        local jitter=$((RANDOM % 3 + 1))
        sleep $((retry_count * 2 + jitter))
    done
}

get_database_size() {
    local pg_cmd_base="psql -h '$DB_HOST' -p '$DB_PORT' -U '$DB_USER' --ssl-mode='$DB_SSL_MODE' --no-password"
    
    eval "$pg_cmd_base -d '$DB_NAME' -t -c \"SELECT pg_size_pretty(pg_database_size('$DB_NAME'));\"" | xargs
}

get_database_size_bytes() {
    eval "psql -h '$DB_HOST' -p '$DB_PORT' -U '$DB_USER' -d '$DB_NAME' --ssl-mode='$DB_SSL_MODE' --no-password -t -c \"SELECT pg_database_size('$DB_NAME');\"" | xargs
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
    
    # pgBackRest has built-in integrity verification
    if command -v pgbackrest &>/dev/null; then
        if pgbackrest --stanza="$PGBACKREST_STANZA" check &>/dev/null; then
            log_success "pgBackRest integrity check passed"
        else
            log_error "pgBackRest integrity check failed"
            return 1
        fi
    fi
    
    # Verify checksum
    if sha256sum -c "$checksum_file" &>/dev/null; then
        log_success "Backup checksum verification passed"
    else
        log_error "Backup checksum verification failed"
        return 1
    fi
    
    rm -f "$verification_log"
    return 0
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
    
    # Apply storage class optimization based on backup type
    local storage_class="STANDARD"
    case "$BACKUP_TYPE" in
        incremental) storage_class="STANDARD" ;;
        differential) storage_class="STANDARD_IA" ;;
        full) storage_class="STANDARD_IA" ;;
    esac
    
    log_info "Using S3 storage class: $storage_class"
    
    # Upload with encryption and metadata, including object tagging
    if aws s3 cp "$backup_file" "$s3_uri" \
       --storage-class "$storage_class" \
       --server-side-encryption AES256 \
       --metadata "database=$DB_NAME,timestamp=$TIMESTAMP,hostname=$(hostname),backup_type=$BACKUP_TYPE" \
       --tagging "BackupType=$BACKUP_TYPE,Database=$DB_NAME,RetentionPeriod=$RETENTION_DAYS,Environment=production" \
       --only-show-errors; then
        
        local end_time=$(date +%s)
        local upload_duration=$((end_time - start_time))
        
        log_success "Upload completed successfully in ${upload_duration}s to storage class: $storage_class"
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
    
    log_info "Creating S3 lifecycle policy with object tagging for automated transitions"
    
    cat > "$policy_file" <<EOF
{
    "Rules": [
        {
            "ID": "PostgreSQL-Full-Backup-Lifecycle",
            "Status": "Enabled",
            "Filter": {
                "And": {
                    "Prefix": "$S3_PREFIX/",
                    "Tags": [
                        {
                            "Key": "BackupType",
                            "Value": "full"
                        }
                    ]
                }
            },
            "Transitions": [
                {
                    "Days": 30,
                    "StorageClass": "STANDARD_IA"
                },
                {
                    "Days": 90,
                    "StorageClass": "GLACIER"
                },
                {
                    "Days": 365,
                    "StorageClass": "DEEP_ARCHIVE"
                }
            ]
        },
        {
            "ID": "PostgreSQL-Differential-Lifecycle",
            "Status": "Enabled",
            "Filter": {
                "And": {
                    "Prefix": "$S3_PREFIX/",
                    "Tags": [
                        {
                            "Key": "BackupType", 
                            "Value": "differential"
                        }
                    ]
                }
            },
            "Transitions": [
                {
                    "Days": 7,
                    "StorageClass": "STANDARD_IA"
                },
                {
                    "Days": 30,
                    "StorageClass": "GLACIER"
                }
            ],
            "Expiration": {
                "Days": $WEEKLY_RETENTION
            }
        },
        {
            "ID": "PostgreSQL-Incremental-Lifecycle",
            "Status": "Enabled",
            "Filter": {
                "And": {
                    "Prefix": "$S3_PREFIX/",
                    "Tags": [
                        {
                            "Key": "BackupType",
                            "Value": "incremental"
                        }
                    ]
                }
            },
            "Transitions": [
                {
                    "Days": 3,
                    "StorageClass": "STANDARD_IA"
                }
            ],
            "Expiration": {
                "Days": $RETENTION_DAYS
            }
        },
        {
            "ID": "WAL-Archive-Lifecycle", 
            "Status": "Enabled",
            "Filter": {
                "Prefix": "$S3_WAL_PREFIX/"
            },
            "Transitions": [
                {
                    "Days": 7,
                    "StorageClass": "STANDARD_IA"
                },
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
                "And": {
                    "Prefix": "$S3_PREFIX/",
                    "Tags": [
                        {
                            "Key": "ComplianceRetention",
                            "Value": "true"
                        }
                    ]
                }
            },
            "Transitions": [
                {
                    "Days": 30,
                    "StorageClass": "STANDARD_IA"
                },
                {
                    "Days": 90,
                    "StorageClass": "GLACIER"
                },
                {
                    "Days": 365,
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
        log_info "S3 lifecycle policy with object tagging configured successfully"
        log_info "Automated transitions: Standard (0-7d) → IA (7-30d) → Glacier (30-90d) → Deep Archive (365d+)"
    else
        log_warn "Failed to configure S3 lifecycle policy"
    fi
    
    rm -f "$policy_file"
}

cleanup_old_backups_s3() {
    log_info "Cleaning up old backups in S3 using tiered retention strategy with lifecycle policies"
    
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
    log_info "Note: S3 lifecycle policies will handle automated transitions and deletions"
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
# WAL ARCHIVING AND PITR FUNCTIONS
# ==============================================================================

setup_wal_archiving() {
    log_info "Setting up PostgreSQL WAL archiving configuration"
    
    # Create WAL archive directory
    local wal_archive_dir="/var/lib/postgresql/wal_archive"
    mkdir -p "$wal_archive_dir"
    chown postgres:postgres "$wal_archive_dir"
    chmod 700 "$wal_archive_dir"
    
    log_info "PostgreSQL Configuration required for WAL archiving:"
    log_info "Add the following to postgresql.conf:"
    log_info "# WAL Archiving Configuration"
    log_info "wal_level = replica"
    log_info "archive_mode = on"
    log_info "archive_command = 'test ! -f $wal_archive_dir/%f && cp %p $wal_archive_dir/%f && aws s3 cp $wal_archive_dir/%f s3://$S3_BUCKET/$S3_WAL_PREFIX/%f --server-side-encryption AES256 --only-show-errors'"
    log_info "archive_timeout = 300  # 5 minutes - force WAL switch every 5 minutes"
    log_info "restore_command = 'aws s3 cp s3://$S3_BUCKET/$S3_WAL_PREFIX/%f %p --only-show-errors'"
    log_info ""
    
    # Create archive command script
    local archive_script="/usr/local/bin/wal_archive.sh"
    cat > "$archive_script" <<'EOF'
#!/bin/bash
WAL_PATH="$1"
WAL_FILE="$(basename "$WAL_PATH")"
ARCHIVE_DIR="/var/lib/postgresql/wal_archive"

# Copy WAL file to local archive first (for safety)
if ! test -f "$ARCHIVE_DIR/$WAL_FILE"; then
    if cp "$WAL_PATH" "$ARCHIVE_DIR/$WAL_FILE"; then
        # Upload to S3 with error handling
        if aws s3 cp "$ARCHIVE_DIR/$WAL_FILE" "s3://S3_BUCKET/S3_WAL_PREFIX/$WAL_FILE" --server-side-encryption AES256 --only-show-errors; then
            echo "WAL file $WAL_FILE archived successfully to S3"
            exit 0
        else
            echo "Failed to upload WAL file $WAL_FILE to S3" >&2
            exit 1
        fi
    else
        echo "Failed to copy WAL file $WAL_FILE to local archive" >&2
        exit 1
    fi
else
    echo "WAL file $WAL_FILE already exists in archive"
    exit 0
fi
EOF
    
    # Substitute variables in the script
    sed -i "s/S3_BUCKET/$S3_BUCKET/g" "$archive_script"
    sed -i "s/S3_WAL_PREFIX/$S3_WAL_PREFIX/g" "$archive_script"
    chmod +x "$archive_script"
    chown postgres:postgres "$archive_script"
    
    log_info "Created WAL archive script: $archive_script"
    
    # Test WAL archiving if possible
    test_wal_archiving
    
    # Implement WAL file copying to S3
    if [[ -d "$wal_archive_dir" ]]; then
        log_info "Syncing existing WAL files from local archive to S3"
        aws s3 sync "$wal_archive_dir/" "s3://$S3_BUCKET/$S3_WAL_PREFIX/" \
            --delete --only-show-errors \
            --exclude "*partial*" || log_warn "Failed to sync WAL files to S3"
    fi
    
    setup_wal_retention_policy
    setup_wal_monitoring
    
    log_info "Recovery objectives:"
    log_info "RPO (Recovery Point Objective): $DR_RPO_HOURS hour(s) maximum data loss"
    log_info "RTO (Recovery Time Objective): $DR_RTO_HOURS hour(s) maximum downtime"
    
    # Calculate backup frequency to meet RPO targets
    local required_backup_frequency=$(( DR_RPO_HOURS * 60 ))
    log_info "To meet RPO of $DR_RPO_HOURS hours, ensure backups run at least every $required_backup_frequency minutes"
}

test_wal_archiving() {
    log_info "Testing WAL archiving functionality"
    
    # Test if PostgreSQL is configured for archiving
    local wal_level
    wal_level=$(psql -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" --ssl-mode="$DB_SSL_MODE" --no-password \
                -d "$DB_NAME" -t -c "SHOW wal_level;" 2>/dev/null | xargs || echo "unknown")
    
    local archive_mode
    archive_mode=$(psql -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" --ssl-mode="$DB_SSL_MODE" --no-password \
                  -d "$DB_NAME" -t -c "SHOW archive_mode;" 2>/dev/null | xargs || echo "unknown")
    
    log_info "Current WAL level: $wal_level"
    log_info "Current archive mode: $archive_mode"
    
    if [[ "$wal_level" == "replica" || "$wal_level" == "logical" ]] && [[ "$archive_mode" == "on" ]]; then
        log_success "PostgreSQL is properly configured for WAL archiving"
        
        # Force WAL switch to test archiving
        if psql -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" --ssl-mode="$DB_SSL_MODE" --no-password \
           -d "$DB_NAME" -c "SELECT pg_switch_wal();" &>/dev/null; then
            log_info "Forced WAL switch to test archiving process"
        fi
    else
        log_warn "PostgreSQL is not properly configured for WAL archiving"
        log_warn "Required: wal_level = replica AND archive_mode = on"
    fi
}

setup_wal_retention_policy() {
    log_info "Setting up WAL file retention policies"
    
    # WAL retention should be longer than backup retention
    local wal_retention_days=$((RETENTION_DAYS + 7))
    
    log_info "WAL files will be retained for $wal_retention_days days"
    log_info "This provides coverage beyond backup retention period"
    
    # Create cleanup script for old local WAL files
    local wal_cleanup_script="/usr/local/bin/wal_cleanup.sh"
    cat > "$wal_cleanup_script" <<EOF
#!/bin/bash
# Clean up local WAL archive files older than $wal_retention_days days
ARCHIVE_DIR="/var/lib/postgresql/wal_archive"
find "\$ARCHIVE_DIR" -name "*.wal" -o -name "[0-9A-F]*" -type f -mtime +$wal_retention_days -delete
EOF
    
    chmod +x "$wal_cleanup_script"
    log_info "Created WAL cleanup script: $wal_cleanup_script"
}

setup_wal_monitoring() {
    log_info "Setting up WAL archiving monitoring"
    
    # Monitor archive status
    local archive_status_check="/usr/local/bin/check_wal_archive.sh"
    cat > "$archive_status_check" <<EOF
#!/bin/bash
# Check WAL archiving status
PGDATA="\$(psql -h $DB_HOST -p $DB_PORT -U $DB_USER -d $DB_NAME --ssl-mode=$DB_SSL_MODE --no-password -t -c "SHOW data_directory;" 2>/dev/null | xargs)"
ARCHIVE_STATUS_DIR="\$PGDATA/pg_wal/archive_status"

if [[ -d "\$ARCHIVE_STATUS_DIR" ]]; then
    ready_count=\$(find "\$ARCHIVE_STATUS_DIR" -name "*.ready" | wc -l)
    if [[ \$ready_count -gt 10 ]]; then
        echo "WARNING: \$ready_count WAL files waiting to be archived"
        exit 1
    else
        echo "WAL archiving is healthy (\$ready_count files pending)"
        exit 0
    fi
else
    echo "ERROR: Cannot find archive_status directory"
    exit 1
fi
EOF
    
    chmod +x "$archive_status_check"
    log_info "Created WAL monitoring script: $archive_status_check"
}

create_pitr_recovery_config() {
    local recovery_time="${1:-}"
    local recovery_config_file="/tmp/postgresql_recovery_${TIMESTAMP}.conf"
    
    log_info "Creating PITR recovery configuration"
    
    cat > "$recovery_config_file" <<EOF
# PostgreSQL recovery configuration for PITR
# Generated by PostgreSQL backup script on $(date)

# Restore command to fetch WAL files from S3
restore_command = 'aws s3 cp s3://$S3_BUCKET/$S3_WAL_PREFIX/%f %p --only-show-errors'

# Recovery target settings
recovery_target_action = 'promote'
recovery_target_timeline = 'current'

EOF

    if [[ -n "$recovery_time" ]]; then
        echo "recovery_target_time = '$recovery_time'" >> "$recovery_config_file"
        echo "# Point-in-time recovery to: $recovery_time" >> "$recovery_config_file"
    else
        echo "# Recover to end of available WAL (latest point)" >> "$recovery_config_file"
    fi
    
    cat >> "$recovery_config_file" <<EOF

# Optional: Pause recovery at target for verification
# recovery_target_action = 'pause'

# Archive settings (disable during recovery)
archive_mode = off
archive_command = ''
EOF
    
    log_info "Recovery configuration written to: $recovery_config_file"
    log_info "Recovery procedure:"
    log_info "1. Stop PostgreSQL"
    log_info "2. Restore base backup to data directory"
    log_info "3. Copy recovery config to data directory as postgresql.conf"
    log_info "4. Start PostgreSQL to begin recovery"
    log_info "5. Monitor recovery progress in PostgreSQL logs"
    
    echo "$recovery_config_file"
}

document_pitr_procedures() {
    local pitr_doc="/tmp/pitr_procedures_${TIMESTAMP}.md"
    
    log_info "Creating comprehensive PITR documentation"
    
    cat > "$pitr_doc" <<EOF
# PostgreSQL Point-in-Time Recovery (PITR) Procedures

## Overview
This document provides step-by-step procedures for performing Point-in-Time Recovery using PostgreSQL base backups and WAL archives.

## Prerequisites
- Base backup available in S3: s3://$S3_BUCKET/$S3_PREFIX/
- WAL archives available in S3: s3://$S3_BUCKET/$S3_WAL_PREFIX/
- AWS CLI configured with access to backup bucket
- Target PostgreSQL server with matching version

## Recovery Time Objectives
- RPO: $DR_RPO_HOURS hours (maximum data loss)
- RTO: $DR_RTO_HOURS hours (maximum recovery time)

## Step-by-Step Recovery Process

### 1. Prepare Recovery Environment
\`\`\`bash
# Stop PostgreSQL if running
systemctl stop postgresql

# Backup current data directory (if any)
mv /var/lib/postgresql/data /var/lib/postgresql/data.backup.\$(date +%s)

# Create new data directory
mkdir -p /var/lib/postgresql/data
chown postgres:postgres /var/lib/postgresql/data
\`\`\`

### 2. Restore Base Backup
\`\`\`bash
# Download and extract latest base backup
aws s3 cp s3://$S3_BUCKET/$S3_PREFIX/latest_backup.tar.gz /tmp/
tar -xzf /tmp/latest_backup.tar.gz -C /var/lib/postgresql/data/

# Or use specific backup timestamp
# aws s3 cp s3://$S3_BUCKET/$S3_PREFIX/backup_YYYY-MM-DD_HH-MM-SS.tar.gz /tmp/
\`\`\`

### 3. Configure Recovery Settings
\`\`\`bash
# Create recovery configuration
cat > /var/lib/postgresql/data/postgresql.conf <<'RECOVERY_EOF'
# Recovery configuration
restore_command = 'aws s3 cp s3://$S3_BUCKET/$S3_WAL_PREFIX/%f %p --only-show-errors'
recovery_target_action = 'promote'
recovery_target_timeline = 'current'

# For specific time recovery, add:
# recovery_target_time = '2024-01-15 14:30:00'

# Disable archiving during recovery
archive_mode = off
archive_command = ''
RECOVERY_EOF
\`\`\`

### 4. Start Recovery Process
\`\`\`bash
# Start PostgreSQL
systemctl start postgresql

# Monitor recovery progress
tail -f /var/log/postgresql/postgresql.log
\`\`\`

### 5. Verify Recovery
\`\`\`bash
# Connect and verify data
psql -c "SELECT now()
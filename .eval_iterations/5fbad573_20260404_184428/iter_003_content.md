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

    # Check for pgBackRest if backup type is not full
    if [[ "$BACKUP_TYPE" != "full" ]] && ! command -v pgbackrest &> /dev/null; then
        missing_deps+=("pgbackrest (required for differential/incremental backups)")
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
    db_size_bytes=$(eval "psql -h '$DB_HOST' -p '$DB_PORT' -U '$DB_USER' -d '$DB_NAME' --ssl-mode='$DB_SSL_MODE' --no-password -t -c \"SELECT pg_database_size('$DB_NAME');\"" | xargs)
    
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
            if pg_restore -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" --ssl-mode="$DB_SSL_MODE" --no-password \
               -d "$test_db" -j "$PARALLEL_JOBS" "$backup_file" &>/dev/null; then
                restore_success=true
            fi
            ;;
        plain)
            if eval "psql -h '$DB_HOST' -p '$DB_PORT' -U '$DB_USER' --ssl-mode='$DB_SSL_MODE' --no-password \
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
    local storage_class="STANDARD_IA"
    
    # Apply storage class optimization based on backup age
    local backup_age_days=$(( ($(date +%s) - $(date -r "$backup_file" +%s)) / 86400 ))
    if [[ $backup_age_days -gt 30 ]]; then
        storage_class="GLACIER"
    elif [[ $backup_age_days -gt 90 ]]; then
        storage_class="DEEP_ARCHIVE"
    fi
    
    # Add encryption at rest with backup file encryption
    local encrypted_file="${backup_file}.gpg"
    if gpg --cipher-algo AES256 --compress-algo 1 --symmetric --batch --yes \
       --passphrase-file <(echo "${GPG_PASSPHRASE:-default_backup_key}") \
       --output "$encrypted_file" "$backup_file" 2>/dev/null; then
        log_info "Backup file encrypted successfully"
        backup_file="$encrypted_file"
    fi
    
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
        
        # Clean up encrypted file
        [[ -f "$encrypted_file" ]] && rm -f "$encrypted_file"
        
        return 0
    else
        log_error "Upload to S3 failed"
        [[ -f "$encrypted_file" ]] && rm -f "$encrypted_file"
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
        log_info "Automated transitions: Standard (0-30d) → IA (30-90d) → Glacier (90-365d) → Deep Archive (365d+)"
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

setup_wal_archiving() {
    log_info "WAL Archiving Configuration Instructions:"
    log_info "Add the following to postgresql.conf:"
    log_info "wal_level = replica"
    log_info "archive_mode = on" 
    log_info "archive_command = 'test ! -f /var/lib/postgresql/wal_archive/%f && cp %p /var/lib/postgresql/wal_archive/%f && aws s3 cp /var/lib/postgresql/wal_archive/%f s3://$S3_BUCKET/$S3_WAL_PREFIX/%f --server-side-encryption AES256 --only-show-errors'"
    log_info "archive_timeout = 300  # 5 minutes"
    log_info "restore_command = 'aws s3 cp s3://$S3_BUCKET/$S3_WAL_PREFIX/%f %p --only-show-errors'"
    log_info ""
    log_info "For Point-in-Time Recovery (PITR):"
    log_info "1. Restore base backup to target directory"
    log_info "2. Create recovery.conf with:"
    log_info "   restore_command = 'aws s3 cp s3://$S3_BUCKET/$S3_WAL_PREFIX/%f %p --only-show-errors'"
    log_info "   recovery_target_time = '2024-01-01 12:00:00'"
    log_info "   recovery_target_action = 'promote'"
    log_info "3. Start PostgreSQL to replay WAL files"
    log_info ""
    log_info "WAL file management and validation:"
    
    # Implement WAL file copying to S3
    local wal_archive_dir="/var/lib/postgresql/wal_archive"
    if [[ -d "$wal_archive_dir" ]]; then
        log_info "Syncing WAL files from local archive to S3"
        aws s3 sync "$wal_archive_dir/" "s3://$S3_BUCKET/$S3_WAL_PREFIX/" \
            --delete --only-show-errors \
            --exclude "*partial*" || log_warn "Failed to sync WAL files to S3"
    fi
    
    log_info "Recovery objectives:"
    log_info "RPO (Recovery Point Objective): $DR_RPO_HOURS hour(s) maximum data loss"
    log_info "RTO (Recovery Time Objective): $DR_RTO_HOURS hour(s) maximum downtime"
    
    # Calculate backup frequency to meet RPO targets
    local required_backup_frequency=$(( DR_RPO_HOURS * 60 ))
    log_info "To meet RPO of $DR_RPO_HOURS hours, ensure backups run at least every $required_backup_frequency minutes"
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
# PGBACKREST ENTERPRISE BACKUP FUNCTIONS
# ==============================================================================

get_backup_type() {
    # Auto-determine backup type based on schedule or use configured type
    if [[ "$BACKUP_TYPE" != "auto" ]]; then
        echo "$BACKUP_TYPE"
        return
    fi
    
    local day_of_week=$(date +%u)
    case $day_of_week in
        7) echo "full" ;;     # Sunday - Full backup
        3) echo "differential" ;;  # Wednesday - Differential backup  
        *) echo "incremental" ;;   # Other days - Incremental backup
    esac
}

perform_pgbackrest_backup() {
    local backup_type=$(get_backup_type)
    local stanza="$DB_NAME"
    
    log_info "Starting $backup_type backup using pgBackRest for stanza: $stanza"
    
    # Check if pgBackRest is configured
    if ! pgbackrest --stanza="$stanza" check &>/dev/null; then
        log_error "pgBackRest stanza '$stanza' not configured or check failed"
        return 1
    fi
    
    local start_time=$(date +%s)
    local backup_options=""
    
    # Configure parallel processing based on CPU cores and database size
    local optimal_jobs=$PARALLEL_JOBS
    local db_size_gb=$(( $(get_database_size_bytes) / 1073741824 ))
    if [[ $db_size_gb -gt 100 ]]; then
        optimal_jobs=$((optimal_jobs * 2))  # Double jobs for large databases
    fi
    
    backup_options="--process-max=$optimal_jobs"
    
    # Add compression and encryption options
    backup_options+=" --compress-type=zst --compress-level=3"
    
    # Execute backup with retry logic
    local retry_count=0
    local max_retries=3
    local backup_success=false
    
    while [[ $retry_count -lt $max_retries ]] && [[ "$backup_success" != "true" ]]; do
        if pgbackrest --stanza="$stanza" --type="$backup_type" $backup_options backup; then
            backup_success=true
        else
            local exit_code=$?
            retry_count=$((retry_count + 1))
            
            case $exit_code in
                40001|40P01)  # Serialization failures
                    if [[ $retry_count -lt $max_retries ]]; then
                        local backoff_time=$((2**retry_count + RANDOM % 3))
                        log_warn "$backup_type backup failed with serialization error, retrying in ${backoff_time}s (attempt $retry_count/$max_retries)"
                        sleep $backoff_time
                        continue
                    fi
                    ;;
                *)
                    log_error "$backup_type backup failed with exit code: $exit_code"
                    break
                    ;;
            esac
        fi
    done
    
    local end_time=$(date +%s)
    local duration=$((end_time - start_time))
    
    if [[ "$backup_success" == "true" ]]; then
        log_success "pgBackRest $backup_type backup completed successfully in ${duration}s"
        
        # Get backup information
        local backup_info=$(pgbackrest --stanza="$stanza" info --output=json)
        local backup_size=$(echo "$backup_info" | jq -r '.[-1].backup[-1]."backup-size"' 2>/dev/null || echo "unknown")
        
        log_info "Backup size: $(human_readable_size ${backup_size:-0})"
        return 0
    else
        log_error "pgBackRest $backup_type backup failed after $max_retries attempts"
        return 1
    fi
}

implement_delta_restore() {
    local backup_path="$1"
    local target_directory="$2"
    local stanza="$DB_NAME"
    
    log_info "Implementing delta restore to $target_directory"
    
    # Use pgBackRest's delta restore capability
    if pgbackrest --stanza="$stanza" --delta \
       --target="$target_directory" \
       --type=time --target-timeline=current \
       restore; then
        log_success "Delta restore completed successfully"
        return 0
    else
        log_error "Delta restore failed"
        return 1
    fi
}

get_database_size_bytes() {
    eval "psql -h '$DB_HOST' -p '$DB_PORT' -U '$DB_USER' -d '$DB_NAME' --ssl-mode='$DB_SSL_MODE' --no-password -t -c \"SELECT pg_database_size('$DB_NAME');\"" | xargs
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
    
    # Use pgBackRest for differential/incremental backups if available
    if [[ "$BACKUP_TYPE" != "full" ]] && command -v pgbackrest &>/dev/null; then
        return perform_pgbackrest_backup
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
    pg_dump_cmd+=" --serializable-deferrable --no-privileges --no-owner --compress=9"
    
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
                    if eval "$pg_
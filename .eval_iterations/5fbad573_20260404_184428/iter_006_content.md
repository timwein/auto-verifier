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
readonly S3_ENCRYPTION_TYPE="${S3_ENCRYPTION_TYPE:-AES256}"  # AES256 or aws:kms
readonly S3_KMS_KEY_ID="${S3_KMS_KEY_ID:-}"

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

    # S3 encryption validation
    [[ ! "$S3_ENCRYPTION_TYPE" =~ ^(AES256|aws:kms)$ ]] && errors+=("S3_ENCRYPTION_TYPE must be 'AES256' or 'aws:kms'")
    if [[ "$S3_ENCRYPTION_TYPE" == "aws:kms" ]] && [[ -z "$S3_KMS_KEY_ID" ]]; then
        errors+=("S3_KMS_KEY_ID is required when S3_ENCRYPTION_TYPE=aws:kms")
    fi

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
        "pg_dump"
        "pg_restore"
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
# PGBACKREST CONFIGURATION FUNCTIONS
# ==============================================================================

setup_pgbackrest_config() {
    log_info "Setting up pgBackRest configuration file"
    
    # Create configuration directory
    mkdir -p "$(dirname "$PGBACKREST_CONFIG_FILE")"
    
    # Generate encryption key if needed
    local cipher_pass=""
    if [[ "$COMPLIANCE_ENABLED" == "true" ]]; then
        cipher_pass=$(openssl rand -base64 48)
        log_info "Generated encryption key for compliance mode"
    fi
    
    # Create pgBackRest configuration
    cat > "$PGBACKREST_CONFIG_FILE" <<EOF
# pgBackRest Configuration
# Generated by PostgreSQL backup script on $(date)

[global]
# Repository configuration
repo1-path=/var/lib/pgbackrest
repo1-retention-full=2
repo1-retention-diff=4
repo1-retention-archive-type=full
repo1-retention-archive=2

# S3 repository configuration
repo2-type=s3
repo2-s3-bucket=$S3_BUCKET
repo2-s3-region=$S3_REGION
repo2-s3-endpoint=s3.$S3_REGION.amazonaws.com
repo2-path=/$S3_PREFIX
repo2-retention-full=4
repo2-retention-diff=8

# Compression and encryption
compress-type=zst
compress-level=3
$(if [[ -n "$cipher_pass" ]]; then
    echo "repo1-cipher-type=aes-256-cbc"
    echo "repo1-cipher-pass=$cipher_pass"
    echo "repo2-cipher-type=aes-256-cbc"
    echo "repo2-cipher-pass=$cipher_pass"
fi)

# Performance settings
process-max=$PARALLEL_JOBS
archive-async=y
archive-push-queue-max=100MB
spool-path=/var/spool/pgbackrest
delta=y

# Logging
log-level-console=info
log-level-file=detail
log-path=/var/log/pgbackrest

# Backup settings
start-fast=y
backup-standby=n

[$PGBACKREST_STANZA]
# PostgreSQL cluster configuration
pg1-path=/var/lib/postgresql/data
pg1-port=$DB_PORT
pg1-host=$DB_HOST
pg1-user=$DB_USER
EOF

    chmod 644 "$PGBACKREST_CONFIG_FILE"
    chown postgres:postgres "$PGBACKREST_CONFIG_FILE" 2>/dev/null || true
    
    log_info "pgBackRest configuration created: $PGBACKREST_CONFIG_FILE"
}

setup_postgresql_archiving() {
    log_info "Configuring PostgreSQL for WAL archiving"
    
    cat <<EOF

# PostgreSQL Configuration for WAL Archiving
# Add the following to your postgresql.conf file:

# WAL archiving configuration
wal_level = replica
archive_mode = on
archive_command = 'pgbackrest --stanza=$PGBACKREST_STANZA archive-push %p'
archive_timeout = 300
max_wal_senders = 3

# Recovery configuration (for restore_command)
restore_command = 'pgbackrest --stanza=$PGBACKREST_STANZA archive-get %f "%p"'

# Additional recommended settings
checkpoint_completion_target = 0.9
wal_buffers = 16MB
wal_compression = on

EOF

    # Test if PostgreSQL configuration allows archiving
    local wal_level
    wal_level=$(psql -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" --ssl-mode="$DB_SSL_MODE" --no-password \
                -d "$DB_NAME" -t -c "SHOW wal_level;" 2>/dev/null | xargs || echo "unknown")
    
    local archive_mode
    archive_mode=$(psql -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" --ssl-mode="$DB_SSL_MODE" --no-password \
                  -d "$DB_NAME" -t -c "SHOW archive_mode;" 2>/dev/null | xargs || echo "unknown")
    
    log_info "Current PostgreSQL configuration:"
    log_info "  wal_level: $wal_level"
    log_info "  archive_mode: $archive_mode"
    
    if [[ "$wal_level" == "replica" || "$wal_level" == "logical" ]] && [[ "$archive_mode" == "on" ]]; then
        log_success "PostgreSQL is properly configured for WAL archiving"
    else
        log_warn "PostgreSQL requires configuration changes for WAL archiving"
        log_warn "Required: wal_level = replica AND archive_mode = on"
    fi
}

# ==============================================================================
# BACKUP INTEGRITY VERIFICATION FUNCTIONS
# ==============================================================================

verify_backup_integrity() {
    local backup_file="$1"
    local verification_log="/tmp/backup_verification_${TIMESTAMP}.log"
    
    log_info "Performing comprehensive backup integrity verification"
    
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
    
    # pg_verifybackup for physical backups (if available)
    if command -v pg_verifybackup &>/dev/null && [[ -d "${backup_file%/*}/base" ]]; then
        if 
pg_verifybackup "${backup_file%/*}" &> "$verification_log"
; then
            log_success "pg_verifybackup integrity check passed"
        else
            log_warn "pg_verifybackup check failed - see $verification_log for details"
        fi
    fi
    
    # Verify pg_dump custom format readability with pg_restore --list
    if [[ "$backup_file" =~ \.dump$ ]]; then
        log_info "Verifying pg_dump backup format readability with pg_restore --list"
        if 
pg_restore -l "$backup_file" > /dev/null 2>&1
; then
            log_success "pg_dump backup format validation passed"
        else
            log_error "pg_dump backup format validation failed"
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
    
    # Perform test restoration
    perform_test_restoration "$backup_file"
    local test_result=$?
    
    rm -f "$verification_log"
    return $test_result
}

perform_test_restoration() {
    local backup_file="$1"
    local test_db="restore_test_${TIMESTAMP}"
    local test_log="/tmp/test_restore_${TIMESTAMP}.log"
    
    log_info "Performing test restoration to verify backup usability"
    
    # Create test database
    if createdb "$test_db" 2>> "$test_log"; then
        log_info "Created test database: $test_db"
    else
        log_error "Failed to create test database"
        return 1
    fi
    
    # Restore backup to test database
    local restore_start=$(date +%s)
    if [[ "$backup_file" =~ \.dump$ ]]; then
        if 
pg_restore -d "$test_db" "$backup_file" 2>> "$test_log"
; then
            local restore_end=$(date +%s)
            local duration=$((restore_end - restore_start))
            log_success "Test restoration completed in ${duration}s"
            
            # Verify restoration by checking table count
            local table_count
            table_count=
$(psql -t -c "SELECT count(*) FROM information_schema.tables WHERE table_schema = 'public'" "$test_db" 2>/dev/null | xargs)

            log_info "Restored $table_count tables in test database"
            
            # Run basic connectivity test
            if psql -d "$test_db" -c "SELECT 1;" &>/dev/null; then
                log_success "Test database connectivity verification passed"
            else
                log_warn "Test database connectivity verification failed"
            fi
        else
            log_error "Test restoration failed"
            dropdb "$test_db" 2>/dev/null || true
            return 1
        fi
    else
        log_info "Skipping test restoration for non-pg_dump backup format"
    fi
    
    # Cleanup test database
    if dropdb "$test_db" 2>> "$test_log"; then
        log_info "Cleaned up test database: $test_db"
    else
        log_warn "Failed to cleanup test database: $test_db"
    fi
    
    rm -f "$test_log"
    return 0
}

# ==============================================================================
# PGBACKREST BACKUP FUNCTIONS
# ==============================================================================

perform_pgbackrest_backup() {
    log_info "Performing pgBackRest backup with type: $BACKUP_TYPE"
    
    # Ensure stanza exists
    if ! pgbackrest --stanza="$PGBACKREST_STANZA" --config="$PGBACKREST_CONFIG_FILE" info &>/dev/null; then
        log_info "Creating pgBackRest stanza: $PGBACKREST_STANZA"
        if ! pgbackrest --stanza="$PGBACKREST_STANZA" --config="$PGBACKREST_CONFIG_FILE" stanza-create; then
            log_error "Failed to create pgBackRest stanza"
            return 1
        fi
    fi
    
    # Perform backup with specific type and parallel processing
    local backup_cmd="pgbackrest --stanza=$PGBACKREST_STANZA --config=$PGBACKREST_CONFIG_FILE"
    backup_cmd+=" --type=$BACKUP_TYPE --process-max=$PARALLEL_JOBS"
    backup_cmd+=" --log-level-console=info backup"
    
    log_info "Starting pgBackRest backup command: $backup_cmd"
    
    local backup_start=$(date +%s)
    if eval "$backup_cmd"; then
        local backup_end=$(date +%s)
        local backup_duration=$((backup_end - backup_start))
        
        log_success "pgBackRest backup completed successfully in ${backup_duration}s"
        
        # Get backup information
        local backup_info
        backup_info=$(pgbackrest --stanza="$PGBACKREST_STANZA" --config="$PGBACKREST_CONFIG_FILE" info --output=json)
        
        # Extract metrics from backup info
        log_metrics "\"backup_type\":\"$BACKUP_TYPE\",\"duration\":$backup_duration,\"parallel_jobs\":$PARALLEL_JOBS"
        
        return 0
    else
        log_error "pgBackRest backup failed"
        return 1
    fi
}

# ==============================================================================
# PG_DUMP FALLBACK FUNCTIONS
# ==============================================================================

perform_pg_dump_backup() {
    log_info "Performing pg_dump backup with serializable isolation and comprehensive optimization"
    
    mkdir -p "$BACKUP_DIR"
    
    local backup_file="$BACKUP_DIR/${DB_NAME}_${TIMESTAMP}.dump"
    local dump_cmd="pg_dump"
    
    # Connection parameters with SSL security and connection timeout
    dump_cmd+=" --host='$DB_HOST' --port='$DB_PORT' --username='$DB_USER'"
    dump_cmd+=" --dbname='$DB_NAME' --no-password"
    
    # SSL mode enforcement for connection security
    export PGSSLMODE="$DB_SSL_MODE"
    
    # Consistent snapshot configuration with serializable isolation
    dump_cmd+=" --serializable-deferrable --verbose"
    
    # Backup optimization flags for performance and compatibility
    dump_cmd+=" --format=custom --compress=9"
    dump_cmd+=" --no-privileges --no-owner"
    
    # Parallel jobs if supported and backup format is custom
    if [[ "$PARALLEL_JOBS" -gt 1 ]] && [[ "$BACKUP_FORMAT" == "custom" ]]; then
        dump_cmd+=" --jobs=$PARALLEL_JOBS"
    fi
    
    # Output file
    dump_cmd+=" --file='$backup_file'"
    
    log_info "Starting pg_dump command with serializable snapshot and optimization flags: $dump_cmd"
    
    # Implement retry logic for serializable snapshot conflicts
    local retry_count=0
    local max_retries=5
    
    while [[ $retry_count -lt $max_retries ]]; do
        local backup_start=$(date +%s)
        
        if eval "$dump_cmd"; then
            local backup_end=$(date +%s)
            local backup_duration=$((backup_end - backup_start))
            local backup_size=$(stat -c%s "$backup_file" 2>/dev/null || echo 0)
            
            log_success "pg_dump backup completed in ${backup_duration}s, size: $(human_readable_size "$backup_size")"
            
            # Verify and upload backup
            if verify_backup_integrity "$backup_file"; then
                upload_to_s3 "$backup_file"
                return 0
            else
                log_error "Backup integrity verification failed"
                return 1
            fi
        else
            local dump_exit_code=$?
            retry_count=$((retry_count + 1))
            
            # Handle serializable snapshot conflicts
            case $dump_exit_code in
                40001|40P01)
                    log_warn "Serializable snapshot conflict (code: $dump_exit_code), retrying... (attempt $retry_count/$max_retries)"
                    if [[ $retry_count -lt $max_retries ]]; then
                        # Exponential backoff with jitter for serializable conflicts
                        local backoff=$((2**retry_count))
                        local jitter=$((RANDOM % 3 + 1))
                        sleep $((backoff + jitter))
                        continue
                    fi
                    ;;
                *)
                    log_error "pg_dump failed with exit code: $dump_exit_code"
                    break
                    ;;
            esac
        fi
    done
    
    log_error "pg_dump backup failed after $max_retries attempts"
    return 1
}

# ==============================================================================
# AWS FUNCTIONS
# ==============================================================================

configure_aws_cli() {
    log_info "Configuring AWS CLI with IAM role authentication and enhanced security"
    
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
    
    # Validate S3 bucket access
    if aws s3 ls "s3://$S3_BUCKET" &>/dev/null; then
        log_success "S3 bucket access verified: $S3_BUCKET"
    else
        log_error "S3 bucket access failed: $S3_BUCKET"
        return 1
    fi
    
    # Configure encryption settings
    if [[ "$S3_ENCRYPTION_TYPE" == "aws:kms" ]] && [[ -n "$S3_KMS_KEY_ID" ]]; then
        # Validate KMS key access
        if aws kms describe-key --key-id "$S3_KMS_KEY_ID" &>/dev/null; then
            log_success "KMS key access verified: $S3_KMS_KEY_ID"
        else
            log_error "KMS key access failed: $S3_KMS_KEY_ID"
            return 1
        fi
    fi
    
    return 0
}

upload_to_s3() {
    local backup_file="$1"
    local s3_key="$S3_PREFIX/$(basename "$backup_file")"
    local s3_uri="s3://$S3_BUCKET/$s3_key"
    
    log_info "Uploading backup to S3 with encryption: $s3_uri"
    
    local start_time=$(date +%s)
    
    # Apply storage class optimization based on backup type
    local storage_class="STANDARD"
    case "$BACKUP_TYPE" in
        incremental) storage_class="STANDARD" ;;
        differential) storage_class="STANDARD_IA" ;;
        full) storage_class="STANDARD_IA" ;;
    esac
    
    log_info "Using S3 storage class: $storage_class"
    
    # Build encryption parameters
    local encryption_params=""
    if [[ "$S3_ENCRYPTION_TYPE" == "AES256" ]]; then
        encryption_params="--sse AES256"
    elif [[ "$S3_ENCRYPTION_TYPE" == "aws:kms" ]]; then
        if [[ -n "$S3_KMS_KEY_ID" ]]; then
            encryption_params="--sse aws:kms --sse-kms-key-id $S3_KMS_KEY_ID"
        else
            encryption_params="--sse aws:kms"
        fi
    fi
    
    # Upload with encryption and metadata, including object tagging
    local upload_cmd="aws s3 cp \"$backup_file\" \"$s3_uri\""
    upload_cmd+=" --storage-class \"$storage_class\""
    upload_cmd+=" $encryption_params"
    upload_cmd+=" --metadata \"database=$DB_NAME,timestamp=$TIMESTAMP,hostname=$(hostname),backup_type=$BACKUP_TYPE\""
    upload_cmd+=" --tagging \"BackupType=$BACKUP_TYPE,Database=$DB_NAME,RetentionPeriod=$RETENTION_DAYS,Environment=production\""
    upload_cmd+=" --only-show-errors"
    
    if [[ "$COMPLIANCE_ENABLED" == "true" ]]; then
        upload_cmd=$(echo "$upload_cmd" | sed 's/--tagging "[^"]*"/& ComplianceRetention=true,LegalHold='"$LEGAL_HOLD_ENABLED"'/')
    fi
    
    log_info "Upload command: $upload_cmd"
    
    if eval "$upload_cmd"; then
        local end_time=$(date +%s)
        local upload_duration=$((end_time - start_time))
        
        log_success "Upload completed successfully in ${upload_duration}s with encryption: $S3_ENCRYPTION_TYPE"
        log_info "S3 location: $s3_uri"
        
        # Upload checksum file
        local checksum_file="${backup_file}.sha256"
        if [[ -f "$checksum_file" ]]; then
            eval "aws s3 cp \"$checksum_file\" \"${s3_uri}.sha256\" $encryption_params --only-show-errors"
        fi
        
        return 0
    else
        log_error "Upload to S3 failed"
        return 1
    fi
}

create_s3_lifecycle_policy() {
    local policy_file="/tmp/s3_lifecycle_policy.json"
    
    log_info "Creating S3 lifecycle policy with automated transitions and compliance support"
    
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
    else
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
    fi

    if aws s3api put-bucket-lifecycle-configuration \
       --bucket "$S3_BUCKET" \
       --lifecycle-configuration file://"$policy_file" &>/dev/null; then
        log_success "S3 lifecycle policy configured with automated transitions"
        log_info "Storage class transitions: Standard (0-30d) → IA (30-90d) → Glacier (90-365d) → Deep Archive (365d+)"
        if [[ "$COMPLIANCE_ENABLED" == "true" ]]; then
            log_info "Compliance retention configured: $COMPLIANCE_RETENTION_YEARS year(s)"
        fi
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
    
    # Implement tiered retention:
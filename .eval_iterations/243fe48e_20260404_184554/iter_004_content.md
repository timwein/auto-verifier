```python
"""
Comprehensive ETL DAG with multi-source ingestion, schema drift handling, 
idempotent upserts, alerting, and retry logic.
"""

from datetime import datetime, timedelta
from typing import Dict, Any, Optional, List
import logging
import pandas as pd
import boto3
import json
from pathlib import Path
import hashlib

from airflow import DAG
from airflow.decorators import task, task_group
from airflow.operators.python import PythonOperator
from airflow.operators.dummy import DummyOperator
from airflow.providers.postgres.operators.postgres import PostgresOperator
from airflow.providers.postgres.hooks.postgres import PostgresHook
from airflow.providers.amazon.aws.hooks.s3 import S3Hook
from airflow.providers.http.hooks.http import HttpHook
from airflow.providers.amazon.aws.sensors.s3 import S3KeySensor
from airflow.providers.http.sensors.http import HttpSensor
from airflow.sensors.sql import SqlSensor
from airflow.utils.task_group import TaskGroup
from airflow.utils.trigger_rule import TriggerRule
from airflow.exceptions import AirflowException
from airflow.models import Variable
from airflow.providers.slack.operators.slack_webhook import SlackWebhookOperator
from airflow.providers.prometheus.hooks.prometheus import PrometheusHook
from great_expectations_provider.operators.great_expectations import GreatExpectationsOperator
from airflow.providers.openlineage.extractors.base import BaseExtractor

# Configure logging
logger = logging.getLogger(__name__)

# External secrets backend configuration using HashiCorp Vault
EXTERNAL_SECRETS_CONFIG = {
    'backend': 'airflow.providers.hashicorp.secrets.vault.VaultBackend',
    'backend_kwargs': {
        'connections_path': 'airflow/connections',
        'variables_path': 'airflow/variables',
        'mount_point': 'airflow',
        'url': '{{ var.value.vault_url }}',
        'auth_type': 'approle',
        'role_id': '{{ var.value.vault_role_id }}',
        'secret_id': '{{ var.value.vault_secret_id }}',
        'kv_engine_version': 2
    }
}

# DAG Configuration with optimized settings
DAG_CONFIG = {
    'dag_id': 'etl_multi_source_pipeline',
    'description': 'Multi-source ETL pipeline with schema drift handling and idempotent upserts',
    'schedule_interval': '0 6 * * *',  # Daily at 6 AM
    'start_date': datetime(2026, 1, 1),
    'catchup': False,
    'max_active_runs': 1,
    'tags': ['etl', 'multi-source', 'production']
}

# Default arguments with comprehensive retry and alerting configuration
default_args = {
    'owner': 'data-engineering-team',
    'depends_on_past': False,
    'email': ['data-alerts@company.com'],
    'email_on_failure': True,
    'email_on_retry': False,
    'retries': 3,
    'retry_delay': timedelta(minutes=5),
    'retry_exponential_backoff': True,
    'max_retry_delay': timedelta(minutes=30),
    'execution_timeout': timedelta(minutes=15),  # Optimized for 15-minute execution windows
    'pool': 'etl_pool',  # Resource pool assignment
    'sla': timedelta(hours=4),  # SLA monitoring
    'sla_miss_callback': lambda context: escalate_sla_breach(context),
    'on_failure_callback': lambda context: send_slack_alert(context, 'FAILURE'),
    'on_retry_callback': lambda context: send_slack_alert(context, 'RETRY'),
}

# Data source configurations for scalable architecture with dynamic task mapping
DATA_SOURCES = [
    {
        'name': 'api_orders', 
        'type': 'rest_api', 
        'priority': 1, 
        'table': 'orders',
        'sensor_config': {
            'poke_interval': 30,
            'timeout': 600,
            'retries': 5
        },
        'quality_thresholds': {
            'completeness': 0.95,
            'null_tolerance': 0.05
        }
    },
    {
        'name': 'customer_data', 
        'type': 's3_parquet', 
        'priority': 1, 
        'table': 'customers',
        'sensor_config': {
            'poke_interval': 300,
            'timeout': 1800,
            'retries': 3
        },
        'quality_thresholds': {
            'completeness': 0.98,
            'null_tolerance': 0.02
        }
    },
    {
        'name': 'product_catalog', 
        'type': 'postgresql', 
        'priority': 1, 
        'table': 'products',
        'sensor_config': {
            'poke_interval': 180,
            'timeout': 900,
            'retries': 3
        },
        'quality_thresholds': {
            'completeness': 0.99,
            'null_tolerance': 0.01
        }
    },
]

def escalate_sla_breach(context: Dict[str, Any]) -> None:
    """Handle SLA miss callback with automated recovery procedures."""
    task_instance = context['task_instance']
    dag_id = context['dag'].dag_id
    
    # Send PagerDuty alert for SLA breach
    if 'critical' in task_instance.task_id:
        send_pagerduty_alert(context, 'SLA_BREACH')
    
    # Log SLA breach for monitoring
    logger.critical(f"SLA breach for {dag_id}.{task_instance.task_id}")

def send_slack_alert(context: Dict[str, Any], alert_type: str) -> None:
    """Send Slack alerts with severity-based routing and escalation logic."""
    task_instance = context['task_instance']
    dag_id = context['dag'].dag_id
    execution_date = context['execution_date']
    
    # Determine alert severity and routing
    if context['task_instance'].try_number > 2:
        severity = 'CRITICAL'
        escalation_channel = '#data-critical-alerts'
    elif alert_type == 'FAILURE':
        severity = 'HIGH'
        escalation_channel = '#data-alerts'
    else:
        severity = 'MEDIUM'
        escalation_channel = '#data-alerts'
    
    message = f"""
    {_get_alert_emoji(severity)} *{alert_type}*: {severity} Severity
    
    *DAG*: {dag_id}
    *Task*: {task_instance.task_id}
    *Execution Date*: {{ ds }}
    *Try Number*: {task_instance.try_number}
    *Log URL*: {task_instance.log_url}
    *Severity*: {severity}
    """
    
    try:
        # Send to appropriate channel based on severity
        slack_webhook = SlackWebhookOperator(
            task_id=f'slack_alert_{alert_type.lower()}',
            http_conn_id='slack_webhook',
            message=message,
            dag=context['dag']
        )
        
        # Escalate to PagerDuty for critical failures
        if severity == 'CRITICAL':
            send_pagerduty_alert(context, alert_type)
            
    except Exception as e:
        logger.error(f"Failed to send Slack alert: {e}")

def _get_alert_emoji(severity: str) -> str:
    """Get emoji based on alert severity."""
    emoji_map = {
        'CRITICAL': '🚨',
        'HIGH': '🔴',
        'MEDIUM': '⚠️',
        'LOW': '🟡'
    }
    return emoji_map.get(severity, '📊')

def send_pagerduty_alert(context: Dict[str, Any], alert_type: str) -> None:
    """Send PagerDuty alerts for critical failures."""
    # Implementation would integrate with PagerDuty API
    logger.critical(f"PagerDuty alert triggered for {alert_type}")

@task_group(group_id="sensor_checks")
def wait_for_sources():
    """Task group for source sensors with optimized poke intervals."""
    
    # API health sensor
    wait_for_api = HttpSensor(
        task_id='wait_for_api',
        http_conn_id='orders_api',
        endpoint='/health',
        poke_interval=30,
        timeout=600,
        retries=5,
        pool='sensor_pool'
    )
    
    # S3 file sensor
    wait_for_s3 = S3KeySensor(
        task_id='wait_for_s3',
        bucket_name='customer-data-bucket',
        bucket_key='customer-data/date={{ ds }}/',
        poke_interval=300,
        timeout=1800,
        retries=3,
        pool='sensor_pool'
    )
    
    # PostgreSQL sensor
    wait_for_db = SqlSensor(
        task_id='wait_for_db',
        conn_id='postgres_default',
        sql='SELECT 1',
        poke_interval=180,
        timeout=900,
        retries=3,
        pool='sensor_pool'
    )
    
    return [wait_for_api, wait_for_s3, wait_for_db]

@task
def validate_data_sources() -> Dict[str, bool]:
    """Validate data source availability with circuit breaker patterns."""
    validation_results = {}
    
    for source in DATA_SOURCES:
        source_name = source['name']
        
        # Check circuit breaker status using templating instead of Variable.get()
        failure_threshold = {{ var.value.circuit_breaker_threshold | default(3) }}
        circuit_breaker_open = '{{ var.value.' + source_name + '_circuit_breaker_open | default("false") }}'
        
        if circuit_breaker_open == 'true':
            logger.warning(f"Circuit breaker open for {source_name}")
            validation_results[source_name] = False
            continue
        
        try:
            if source['type'] == 'rest_api':
                http_hook = HttpHook(
                    method='GET', 
                    http_conn_id='orders_api',
                    pool_connections=5,
                    pool_maxsize=10
                )
                response = http_hook.run('/health')
                validation_results[source_name] = response.status_code == 200
                
            elif source['type'] == 's3_parquet':
                s3_hook = S3Hook(aws_conn_id='aws_default')
                validation_results[source_name] = s3_hook.check_for_bucket('customer-data-bucket')
                
            elif source['type'] == 'postgresql':
                postgres_hook = PostgresHook(postgres_conn_id='postgres_default')
                postgres_hook.get_records("SELECT 1")
                validation_results[source_name] = True
                
        except Exception as e:
            logger.error(f"Validation failed for {source_name}: {e}")
            validation_results[source_name] = False
    
    # Raise exception if any validation fails
    failed_sources = [source for source, status in validation_results.items() if not status]
    if failed_sources:
        raise AirflowException(f"Data source validation failed for: {failed_sources}")
    
    return validation_results

@task_group(group_id="extraction")
def extract_all_sources():
    """Parallel extraction from all sources with TaskGroup organization."""
    
    @task(
        task_id='extract_api_orders',
        retries=5,
        execution_timeout=timedelta(minutes=5),
        pool='extraction_pool'
    )
    def extract_rest_api_data() -> str:
        """Extract data from REST API with robust error handling."""
        try:
            http_hook = HttpHook(
                method='GET', 
                http_conn_id='orders_api',
                pool_connections=5,
                pool_maxsize=10
            )
            
            # Add pagination support and date filtering with templating
            params = {
                'date': '{{ ds }}',
                'limit': 1000,
                'offset': 0
            }
            
            all_data = []
            has_more = True
            
            while has_more:
                response = http_hook.run(
                    endpoint='/api/orders',
                    data=params,
                    headers={'Content-Type': 'application/json'}
                )
                
                if response.status_code != 200:
                    raise AirflowException(f"API request failed: {response.status_code}")
                
                data = response.json()
                all_data.extend(data.get('orders', []))
                
                # Check if there's more data
                has_more = len(data.get('orders', [])) == params['limit']
                params['offset'] += params['limit']
            
            # Store extracted data with templated key
            s3_hook = S3Hook(aws_conn_id='aws_default')
            s3_key = 'raw-data/orders/date={{ ds }}/orders.json'
            
            s3_hook.load_string(
                string_data=json.dumps(all_data),
                key=s3_key,
                bucket_name='etl-staging-bucket',
                replace=True
            )
            
            # Collect metrics
            _collect_extraction_metrics('orders', len(all_data))
            
            logger.info(f"Extracted {len(all_data)} records from API")
            return s3_key
            
        except Exception as e:
            logger.error(f"API extraction failed: {e}")
            raise

    @task(
        task_id='extract_s3_customers',
        retries=3,
        execution_timeout=timedelta(minutes=5),
        pool='extraction_pool'
    )
    def extract_s3_parquet_data() -> str:
        """Extract and validate Parquet data from S3."""
        try:
            s3_hook = S3Hook(aws_conn_id='aws_default')
            
            # List files with templated prefix
            s3_prefix = 'customer-data/date={{ ds }}/'
            file_keys = s3_hook.list_keys(
                bucket_name='customer-data-bucket',
                prefix=s3_prefix
            )
            
            if not file_keys:
                raise AirflowException(f"No customer data files found for date {{ ds }}")
            
            # Download and validate Parquet files
            all_dataframes = []
            for key in file_keys:
                if key.endswith('.parquet'):
                    file_obj = s3_hook.get_key(key, 'customer-data-bucket')
                    df = pd.read_parquet(file_obj.get()['Body'])
                    all_dataframes.append(df)
            
            if not all_dataframes:
                raise AirflowException("No valid Parquet files found")
            
            # Combine all dataframes
            combined_df = pd.concat(all_dataframes, ignore_index=True)
            
            # Store processed data with templated key
            output_key = 'processed-data/customers/date={{ ds }}/customers.parquet'
            parquet_buffer = combined_df.to_parquet()
            
            s3_hook.load_bytes(
                bytes_data=parquet_buffer,
                key=output_key,
                bucket_name='etl-staging-bucket',
                replace=True
            )
            
            # Collect metrics
            _collect_extraction_metrics('customers', len(combined_df))
            
            logger.info(f"Processed {len(combined_df)} customer records")
            return output_key
            
        except Exception as e:
            logger.error(f"S3 Parquet extraction failed: {e}")
            raise

    @task(
        task_id='extract_pg_products',
        retries=3,
        execution_timeout=timedelta(minutes=5),
        pool='extraction_pool'
    )
    def extract_postgresql_data() -> str:
        """Extract data from PostgreSQL with incremental loading support."""
        try:
            postgres_hook = PostgresHook(postgres_conn_id='postgres_default')
            
            # Get the last successful run timestamp using templating
            last_run_query = """
            SELECT COALESCE(MAX(last_updated), '1900-01-01'::timestamp) as last_run 
            FROM etl_metadata 
            WHERE table_name = %s AND execution_date = %s AND status = 'success'
            """
            
            last_run_result = postgres_hook.get_records(
                last_run_query, 
                parameters=['products', '{{ ds }}']
            )
            last_run_time = last_run_result[0][0] if last_run_result else datetime(1900, 1, 1)
            
            # Extract incremental data with templated execution date
            extract_query = """
            SELECT product_id, product_name, category, price, supplier_id, 
                   created_at, updated_at
            FROM products 
            WHERE updated_at > %s
            ORDER BY updated_at
            """
            
            df = postgres_hook.get_pandas_df(extract_query, parameters=[last_run_time])
            
            if df.empty:
                logger.info("No new product data to process")
                return ""
            
            # Store extracted data with templated key
            s3_hook = S3Hook(aws_conn_id='aws_default')
            output_key = 'raw-data/products/date={{ ds }}/products.parquet'
            
            parquet_buffer = df.to_parquet()
            s3_hook.load_bytes(
                bytes_data=parquet_buffer,
                key=output_key,
                bucket_name='etl-staging-bucket',
                replace=True
            )
            
            # Collect metrics
            _collect_extraction_metrics('products', len(df))
            
            logger.info(f"Extracted {len(df)} product records")
            return output_key
            
        except Exception as e:
            logger.error(f"PostgreSQL extraction failed: {e}")
            raise
    
    # Return tasks for parallel execution
    return [extract_rest_api_data(), extract_s3_parquet_data(), extract_postgresql_data()]

def _collect_extraction_metrics(table_name: str, record_count: int) -> None:
    """Collect comprehensive extraction metrics with Prometheus integration."""
    try:
        prometheus_hook = PrometheusHook(prometheus_conn_id='prometheus_default')
        
        # Collect volume metrics
        volume_metrics = {
            'etl_extraction_records_total': {
                'value': record_count,
                'labels': {
                    'table_name': table_name,
                    'execution_date': '{{ ds }}',
                    'dag_id': '{{ dag.dag_id }}'
                }
            },
            'etl_extraction_timestamp': {
                'value': '{{ ts }}',
                'labels': {'table_name': table_name}
            }
        }
        
        # Send metrics to Prometheus
        for metric_name, metric_data in volume_metrics.items():
            prometheus_hook.push_metrics(metric_name, metric_data['value'], metric_data['labels'])
            
        # Store metrics in S3 for dashboard creation
        metrics_data = {
            'table_name': table_name,
            'record_count': record_count,
            'extraction_timestamp': '{{ ts }}',
            'execution_date': '{{ ds }}',
            'dag_run_id': '{{ run_id }}',
            'performance_metrics': {
                'extraction_rate_per_minute': record_count / 5,  # assuming 5-minute execution
                'data_volume_mb': _estimate_data_volume(record_count, table_name)
            }
        }
        
        s3_hook = S3Hook(aws_conn_id='aws_default')
        metrics_key = f"metrics/extraction/{table_name}/date={{ ds }}/metrics_{{ ts_nodash }}.json"
        
        s3_hook.load_string(
            string_data=json.dumps(metrics_data),
            key=metrics_key,
            bucket_name='etl-metrics-bucket',
            replace=True
        )
        
        logger.info(f"Metrics collected for {table_name}: {record_count} records")
        
    except Exception as e:
        logger.error(f"Failed to collect metrics for {table_name}: {e}")

def _estimate_data_volume(record_count: int, table_name: str) -> float:
    """Estimate data volume in MB based on table characteristics."""
    volume_estimates = {
        'orders': 0.5,      # KB per record
        'customers': 0.3,   
        'products': 0.2
    }
    
    kb_per_record = volume_estimates.get(table_name, 0.4)
    return (record_count * kb_per_record) / 1024  # Convert to MB

@task_group(group_id="validation")
def validate_all_schemas():
    """Parallel schema validation for all sources."""
    
    @task(
        task_id='validate_orders_schema',
        execution_timeout=timedelta(minutes=5)
    )
    def validate_orders_schema(s3_key: str) -> Dict[str, Any]:
        """Validate orders schema with automated detection and versioning."""
        return _validate_schema_with_versioning(s3_key, 'orders')
    
    @task(
        task_id='validate_customers_schema',
        execution_timeout=timedelta(minutes=5)
    )
    def validate_customers_schema(s3_key: str) -> Dict[str, Any]:
        """Validate customers schema with automated detection and versioning."""
        return _validate_schema_with_versioning(s3_key, 'customers')
    
    @task(
        task_id='validate_products_schema',
        execution_timeout=timedelta(minutes=5)
    )
    def validate_products_schema(s3_key: str) -> Dict[str, Any]:
        """Validate products schema with automated detection and versioning."""
        return _validate_schema_with_versioning(s3_key, 'products')
    
    # Quality gates that check validation results and conditionally trigger downstream tasks
    @task(
        task_id='schema_quality_gate',
        trigger_rule=TriggerRule.NONE_FAILED_MIN_ONE_SUCCESS,
        execution_timeout=timedelta(minutes=5)
    )
    def schema_quality_gate(orders_validation: Dict[str, Any], 
                           customers_validation: Dict[str, Any], 
                           products_validation: Dict[str, Any]) -> Dict[str, Any]:
        """Quality gate that stops pipeline on critical schema failures."""
        gate_results = {
            'orders': orders_validation.get('validation_passed', False),
            'customers': customers_validation.get('validation_passed', False),
            'products': products_validation.get('validation_passed', False),
            'gate_passed': True
        }
        
        # Check for critical schema failures
        breaking_changes = {{ var.value.breaking_change_tolerance | default(0) }} == 0
        failed_validations = [table for table, passed in gate_results.items() 
                            if table != 'gate_passed' and not passed]
        
        if failed_validations and breaking_changes:
            gate_results['gate_passed'] = False
            raise AirflowException(f"Quality gate failed for: {failed_validations}")
        
        return gate_results
    
    # Get extraction outputs and validate in parallel
    extraction_outputs = extract_all_sources()
    
    orders_val = validate_orders_schema(extraction_outputs[0])
    customers_val = validate_customers_schema(extraction_outputs[1])
    products_val = validate_products_schema(extraction_outputs[2])
    
    gate_result = schema_quality_gate(orders_val, customers_val, products_val)
    
    return [orders_val, customers_val, products_val, gate_result]

def _validate_schema_with_versioning(s3_key: str, table_name: str) -> Dict[str, Any]:
    """Enhanced schema validation with versioning and automated registry updates."""
    if not s3_key:
        return {'drift_detected': False, 'validation_passed': True}
    
    try:
        s3_hook = S3Hook(aws_conn_id='aws_default')
        
        # Load current data schema
        if s3_key.endswith('.json'):
            file_obj = s3_hook.get_key(s3_key, 'etl-staging-bucket')
            data = json.loads(file_obj.get()['Body'].read())
            current_schema = _infer_json_schema(data)
        else:
            file_obj = s3_hook.get_key(s3_key, 'etl-staging-bucket')
            df = pd.read_parquet(file_obj.get()['Body'])
            current_schema = _infer_dataframe_schema(df)
        
        # Generate schema fingerprint for change detection
        current_fingerprint = _generate_schema_fingerprint(current_schema)
        
        # Load expected schema from versioned registry
        expected_schema = _load_expected_schema_with_versioning(table_name)
        expected_fingerprint = _generate_schema_fingerprint(expected_schema) if expected_schema else None
        
        # Automated change detection using fingerprinting
        if expected_fingerprint and current_fingerprint != expected_fingerprint:
            drift_detected = True
            logger.info(f"Schema drift detected for {table_name}: fingerprints don't match")
        else:
            drift_detected = False
        
        # Get configurable drift tolerance using templating instead of Variable.get()
        tolerance_level = '{{ var.value.schema_drift_tolerance | default("strict") }}'
        
        # Detect schema drift with configurable tolerance
        drift_analysis = _analyze_schema_drift_with_tolerance(
            expected_schema, 
            current_schema, 
            tolerance_level
        )
        
        # Implement forward and backward compatibility handling
        compatibility_result = _handle_schema_compatibility(
            expected_schema, 
            current_schema, 
            drift_analysis,
            table_name
        )
        
        # Update schema registry if compatible changes detected
        if drift_analysis['has_compatible_changes'] or compatibility_result['can_auto_migrate']:
            _update_schema_registry(table_name, current_schema)
        
        validation_result = {
            'table_name': table_name,
            'drift_detected': drift_analysis['has_drift'],
            'validation_passed': not drift_analysis['has_breaking_changes'],
            'drift_details': drift_analysis,
            'compatibility_result': compatibility_result,
            'current_schema': current_schema,
            'schema_version': _get_next_schema_version(table_name),
            's3_key': s3_key,
            'validation_timestamp': '{{ ts }}',
            'fingerprint': current_fingerprint
        }
        
        # Quality gates with configurable thresholds using templating
        if drift_analysis['has_breaking_changes'] and not compatibility_result['can_graceful_degrade']:
            breaking_tolerance = {{ var.value.breaking_change_tolerance | default(0) }}
            if breaking_tolerance == 0:
                raise AirflowException(f"Breaking schema changes detected for {table_name}")
        
        return validation_result
        
    except Exception as e:
        logger.error(f"Schema validation failed for {table_name}: {e}")
        raise

def _generate_schema_fingerprint(schema: Dict[str, str]) -> str:
    """Generate unique fingerprint for schema change detection."""
    if not schema:
        return ""
    
    # Create deterministic string representation of schema
    schema_str = json.dumps(schema, sort_keys=True)
    
    # Generate MD5 hash for fingerprinting
    return hashlib.md5(schema_str.encode()).hexdigest()

def _handle_schema_compatibility(expected: Dict[str, str], current: Dict[str, str], 
                                drift_analysis: Dict[str, Any], table_name: str) -> Dict[str, Any]:
    """Implement forward and backward compatibility handling with graceful degradation."""
    
    compatibility_result = {
        'forward_compatible': False,
        'backward_compatible': False,
        'can_auto_migrate': False,
        'can_graceful_degrade': False,
        'migration_strategy': None
    }
    
    # Forward compatibility: Handle new columns added to source
    if drift_analysis.get('new_columns'):
        # New columns are generally forward compatible
        compatibility_result['forward_compatible'] = True
        compatibility_result['can_auto_migrate'] = True
        compatibility_result['migration_strategy'] = {
            'type': 'additive_migration',
            'new_columns': drift_analysis['new_columns'],
            'default_values': _generate_default_values(drift_analysis['new_columns'], table_name)
        }
        
        logger.info(f"Forward compatibility: Adding new columns for {table_name}: {drift_analysis['new_columns']}")
    
    # Backward compatibility: Handle deprecated fields gracefully
    if drift_analysis.get('removed_columns'):
        # Check if removed columns are in deprecation list
        deprecated_columns = _get_deprecated_columns(table_name)
        
        removed_deprecated = set(drift_analysis['removed_columns']).intersection(set(deprecated_columns))
        
        if removed_deprecated:
            compatibility_result['backward_compatible'] = True
            compatibility_result['can_graceful_degrade'] = True
            compatibility_result['migration_strategy'] = {
                'type': 'deprecation_migration',
                'removed_deprecated_columns': list(removed_deprecated),
                'fallback_strategy': 'use_defaults_or_nulls'
            }
            
            logger.info(f"Backward compatibility: Gracefully handling deprecated columns for {table_name}")
        else:
            # Non-deprecated columns removed - this is a breaking change
            logger.warning(f"Breaking change: Required columns removed from {table_name}: {drift_analysis['removed_columns']}")
    
    # Type compatibility: Handle compatible type changes
    if drift_analysis.get('type_changes'):
        compatible_type_changes = [tc for tc in drift_analysis['type_changes'] 
                                 if _is_compatible_type_change(tc)]
        
        if compatible_type_changes:
            compatibility_result['can_auto_migrate'] = True
            if not compatibility_result['migration_strategy']:
                compatibility_result['migration_strategy'] = {}
            
            compatibility_result['migration_strategy']['type_migrations'] = compatible_type_changes
            
            logger.info(f"Compatible type changes detected for {table_name}: {compatible_type_changes}")
    
    return compatibility_result

def _get_deprecated_columns(table_name: str) -> List[str]:
    """Get list of deprecated columns for a table from configuration."""
    deprecated_mapping = {
        'orders': ['legacy_order_id', 'old_status_field'],
        'customers': ['deprecated_address_field'],
        'products': ['legacy_category_id']
    }
    
    return deprecated_mapping.get(table_name, [])

def _generate_default_values(new_columns: List[str], table_name: str) -> Dict[str, Any]:
    """Generate appropriate default values for new columns."""
    defaults = {}
    
    for column in new_columns:
        # Intelligent default value generation based on column names and table context
        if 'id' in column.lower():
            defaults[column] = None  # IDs should be nullable by default
        elif 'date' in column.lower() or 'time' in column.lower():
            defaults[column] = '{{ ts }}'  # Use current timestamp
        elif 'flag' in column.lower() or 'is_' in column.lower():
            defaults[column] = False
        elif 'count' in column.lower() or 'amount' in column.lower():
            defaults[column] = 0
        else:
            defaults[column] = None
    
    return defaults

def _analyze_schema_drift_with_tolerance(expected: Dict[str, str], current: Dict[str, str], tolerance: str) -> Dict[str, Any]:
    """Enhanced drift analysis with configurable tolerance levels."""
    if not expected:
        return {
            'has_drift': False,
            'has_breaking_changes': False,
            'has_compatible_changes': True,
            'new_columns': list(current.keys()),
            'removed_columns': [],
            'type_changes': []
        }
    
    new_columns = set(current.keys()) - set(expected.keys())
    removed_columns = set(expected.keys()) - set(current.keys())
    
    type_changes = []
    for column in set(current.keys()) & set(expected.keys()):
        if current[column] != expected[column]:
            type_changes.append({
                'column': column,
                'expected': expected[column],
                'current': current[column]
            })
    
    # Apply tolerance-based evaluation
    has_drift = bool(new_columns or removed_columns or type_changes)
    
    if tolerance == 'strict':
        has_breaking_changes = bool(removed_columns or type_changes)
    elif tolerance == 'moderate':
        # Allow optional new columns and compatible type changes
        has_breaking_changes = bool(removed_columns or 
                                  [tc for tc in type_changes if not _is_compatible_type_change(tc)])
    elif tolerance == 'permissive':
        # Only consider removed required columns as breaking
        has_breaking_changes = bool(removed_columns)
    else:
        has_breaking_changes = bool(removed_columns or type_changes)
    
    return {
        'has_drift': has_drift,
        'has_breaking_changes': has_breaking_changes,
        'has_compatible_changes': bool(new_columns and not has_breaking_changes),
        'new_columns': list(new_columns),
        'removed_columns': list(removed_columns),
        'type_changes': type_changes,
        'tolerance_applied': tolerance
    }

def _is_compatible_type_change(type_change: Dict[str, str]) -> bool:
    """Check if type change is compatible (e.g., int to float)."""
    expected_type = type_change['expected']
    current_type = type_change['current']
    
    # Define compatible type transitions
    compatible_transitions = {
        ('integer', 'float'): True,
        ('string', 'object'): True,
        ('int64', 'float64'): True,
        ('varchar', 'text'): True,
        # Add more as needed
    }
    
    return compatible_transitions.get((expected_type, current_type), False)

def _infer_json_schema(data: List[Dict[str, Any]]) -> Dict[str, str]:
    """Infer schema from JSON data."""
    if not data:
        return {}
    
    schema = {}
    sample_record = data[0] if isinstance(data, list) else data
    
    for key, value in sample_record.items():
        if isinstance(value, bool):
            schema[key] = 'boolean'
        elif isinstance(value, int):
            schema[key] = 'integer'
        elif isinstance(value, float):
            schema[key] = 'float'
        elif isinstance(value, str):
            schema[key] = 'string'
        elif value is None:
            schema[key] = 'null'
        else:
            schema[key] = 'object'
    
    return schema

def _infer_dataframe_schema(df: pd.DataFrame) -> Dict[str, str]:
    """Infer schema from pandas DataFrame."""
    schema = {}
    
    for column, dtype in df.dtypes.items():
        if pd.api.types.is_bool_dtype(dtype):
            schema[column] = 'boolean'
        elif pd.api.types.is_integer_dtype(dtype):
            schema[column] = 'integer'
        elif pd.api.types.is_float_dtype(dtype):
            schema[column] = 'float'
        elif pd.api.types.is_string_dtype(dtype) or pd.api.types.is_object_dtype(dtype):
            schema[column] = 'string'
        elif pd.api.types.is_datetime64_any_dtype(dtype):
            schema[column] = 'timestamp'
        else:
            schema[column] = str(dtype)
    
    return schema

def _load_expected_schema_with_versioning(table_name: str) -> Dict[str, str]:
    """Load expected schema from versioned registry."""
    try:
        s3_hook = S3Hook(aws_conn_id='aws_default')
        
        # Try to load latest schema from registry
        schema_key = f"schema-registry/{table_name}_schema.json"
        
        if s3_hook.check_for_key(schema_key, 'etl-config-bucket'):
            file_obj = s3_hook.get_key(schema_key, 'etl-config-bucket')
            schema_document = json.loads(file_obj.get()['Body'].read())
            return schema_document.get('schema', {})
        else:
            # No existing schema - this is a new table
            logger.info(f"No existing schema found for {table_name}")
            return {}
            
    except Exception as e:
        logger.error(f"Failed to load expected schema for {table_name}: {e}")
        return {}

def _update_schema_registry(table_name: str, schema: Dict[str, str]) -> None:
    """Update schema registry with automated migration capabilities."""
    try:
        s3_hook = S3Hook(aws_conn_id='aws_default')
        
        # Get current schema version
        current_version = _get_next_schema_version(table_name)
        
        schema_document = {
            'schema': schema,
            'version': current_version,
            'updated_at': '{{ ts }}',
            'migration_path': _generate_migration_path(table_name, schema)
        }
        
        schema_key = f"schema-registry/{table_name}_schema_v{current_version}.json"
        
        s3_hook.load_string(
            string_data=json.dumps(schema_document),
            key=schema_key,
            bucket_name='etl-config-bucket',
            replace=True
        )
        
        # Update latest schema pointer
        latest_key = f"schema-registry/{table_name}_schema.json"
        s3_hook.load_string(
            string_data=json.dumps(schema_document),
            key=latest_key,
            bucket_name='etl-config-bucket',
            replace=True
        )
        
        logger.info(f"Schema registry updated for {table_name} version {current_version}")
        
    except Exception as e:
        logger.error(f"Failed to update schema registry: {e}")

def _generate_migration_path(table_name: str, schema: Dict[str, str]) -> Dict[str, Any]:
    """Generate automated migration path for schema changes."""
    return {
        'rollback_strategy': 'version_rollback',
        'migration_sql': f"-- Auto-generated migration for {table_name}",
        'validation_rules': _generate_validation_rules(schema)
    }

def _generate_validation_rules(schema: Dict[str, str]) -> Dict[str, Any]:
    """Generate validation rules based on schema."""
    rules = {}
    
    for column, data_type in schema.items():
        if data_type in ['integer', 'float']:
            rules[column] = {'type': 'numeric', 'nullable': True}
        elif data_type == 'string':
            rules[column] = {'type': 'string', 'max_length': 255, 'nullable': True}
        elif data_type == 'boolean':
            rules[column] = {'type': 'boolean', 'nullable': True}
    
    return rules

def _get_next_schema_version(table_name: str) -> str:
    """Get next schema version number using templated versioning."""
    # Use templated version instead of Variable.get()
    current_version = '{{ var.value.' + table_name + '_schema_version | default("1.0.0") }}'
    try:
        # Implement semantic versioning increment logic
        major, minor, patch = current_version.split('.')
        next_version = f"{major}.{int(minor) + 1}.{patch}"
        return next_version
    except:
        return '1.0.0'

@task_group(group_id="transformation")
def transform_all_data():
    """Parallel transformation for all sources with schema adaptation."""
    
    @task(
        task_id='transform_orders',
        execution_timeout=timedelta(minutes=10),
        pool='transform_pool'
    )
    def transform_orders_data(validation_result: Dict[str, Any]) -> str:
        """Transform orders data with separate schema adaptation."""
        return _transform_data_atomic(validation_result, 'orders')
    
    @task(
        task_id='apply_orders_schema_adaptations',
        execution_timeout=timedelta(minutes=5)
    )
    def apply_orders_adaptations(transformed_key: str, validation_result: Dict[str, Any]) -> str:
        """Apply schema adaptations for orders (separate atomic task)."""
        return _apply_schema_adaptations_atomic(transformed_key, validation_result)
    
    @task(
        task_id='transform_customers',
        execution_timeout=timedelta(minutes=10),
        pool='transform_pool'
    )
    def transform_customers_data(validation_result: Dict[str, Any]) -> str:
        """Transform customers data with separate schema adaptation."""
        return _transform_data_atomic(validation_result, 'customers')
    
    @task(
        task_id='apply_customers_schema_adaptations',
        execution_timeout=timedelta(minutes=5)
    )
    def apply_customers_adaptations(transformed_key: str, validation_result: Dict[str, Any]) -> str:
        """Apply schema adaptations for customers (separate atomic task)."""
        return _apply_schema_adaptations_atomic(transformed_key, validation_result)
    
    @task(
        task_id='transform_products',
        execution_timeout=timedelta(minutes=10),
        pool='transform_pool'
    )
    def transform_products_data(validation_result: Dict[str, Any]) -> str:
        """Transform products data with separate schema adaptation."""
        return _transform_data_atomic(validation_result, 'products')
    
    @task(
        task_id='apply_products_schema_adaptations',
        execution_timeout=timedelta(minutes=5)
    )
    def apply_products_adaptations(transformed_key: str, validation_result: Dict[str, Any]) -> str:
        """Apply schema adaptations for products (separate atomic task)."""
        return _apply_schema_adaptations_atomic(transformed_key, validation_result)
    
    # Get validation outputs and transform in parallel
    validation_outputs = validate_all_schemas()
    
    # Transform data (parallel)
    orders_transformed = transform_orders_data(validation_outputs[0])
    customers_transformed = transform_customers_data(validation_outputs[1])
    products_transformed = transform_products_data(validation_outputs[2])
    
    # Apply adaptations (parallel, dependent on transforms)
    orders_final = apply_orders_adaptations(orders_transformed, validation_outputs[0])
    customers_final = apply_customers_adaptations(customers_transformed, validation_outputs[1])
    products_final = apply_products_adaptations(products_transformed, validation_outputs[2])
    
    return [orders_final, customers_final, products_final]

def _transform_data_atomic(validation_result: Dict[str, Any], table_name: str) -> str:
    """Atomic transformation function without schema adaptation."""
    if not validation_result.get('s3_key'):
        logger.info(f"No data to transform for {table_name}")
        return ""
    
    try:
        s3_hook = S3Hook(aws_conn_id='aws_default')
        s3_key = validation_result['s3_key']
        
        # Load and transform data based on table type
        if table_name == 'orders':
            transformed_df = _transform_orders_data(s3_hook, s3_key)
        elif table_name == 'customers':
            transformed_df = _transform_customers_data(s3_hook, s3_key)
        elif table_name == 'products':
            transformed_df = _transform_products_data(s3_hook, s3_key)
        else:
            raise AirflowException(f"Unknown table: {table_name}")
        
        # Store transformed data with templated key
        output_key = f'transformed-data/{table_name}/date={{ ds }}/{table_name}_transformed.parquet'
        parquet_buffer = transformed_df.to_parquet()
        
        s3_hook.load_bytes(
            bytes_data=parquet_buffer,
            key=output_key,
            bucket_name='etl-staging-bucket',
            replace=True
        )
        
        logger.info(f"Transformed {len(transformed_df)} records for {table_name}")
        return output_key
        
    except Exception as e:
        logger.error(f"Data transformation failed for {table_name}: {e}")
        raise

def _transform_orders_data(s3_hook: S3Hook, s3_key: str) -> pd.DataFrame:
    """Transform orders data with business logic."""
    # Load JSON data
    file_obj = s3_hook.get_key(s3_key, 'etl-staging-bucket')
    data = json.loads(file_obj.get()['Body'].read())
    df = pd.DataFrame(data)
    
    # Apply transformations
    df['order_date'] = pd.to_datetime(df['order_date'])
    df['order_total'] = pd.to_numeric(df['order_total'], errors='coerce')
    df['processed_at'] = '{{ ts }}'
    
    return df

def _transform_customers_data(s3_hook: S3Hook, s3_key: str) -> pd.DataFrame:
    """Transform customers data with business logic."""
    # Load Parquet data
    file_obj = s3_hook.get_key(s3_key, 'etl-staging-bucket')
    df = pd.read_parquet(file_obj.get()['Body'])
    
    # Apply transformations
    df['full_name'] = df['first_name'] + ' ' + df['last_name
```json
{
  "$schema": "https://json-schema.org/draft/2019-09/schema",
  "$id": "https://example.com/saas-billing-schema.json",
  "title": "Multi-Tenant SaaS Billing System Schema",
  "description": "Comprehensive JSON schema for a multi-tenant SaaS billing system supporting usage-based and seat-based pricing with robust financial audit trail",
  "type": "object",
  "properties": {
    "tenants": {
      "type": "array",
      "description": "Collection of tenant organizations in the multi-tenant system",
      "items": {
        "$ref": "#/$defs/tenant"
      }
    },
    "billing_accounts": {
      "type": "array", 
      "description": "Financial accounts for billing and payment tracking",
      "items": {
        "$ref": "#/$defs/billing_account"
      }
    },
    "subscription_plans": {
      "type": "array",
      "description": "Available subscription plans with pricing configurations",
      "items": {
        "$ref": "#/$defs/subscription_plan"
      }
    },
    "subscriptions": {
      "type": "array",
      "description": "Active and historical subscription records",
      "items": {
        "$ref": "#/$defs/subscription"
      }
    },
    "usage_events": {
      "type": "array",
      "description": "Usage events for usage-based billing tracking",
      "items": {
        "$ref": "#/$defs/usage_event"
      }
    },
    "usage_aggregations": {
      "type": "array",
      "description": "Pre-computed usage aggregations for billing periods",
      "items": {
        "$ref": "#/$defs/usage_aggregation"
      }
    },
    "invoices": {
      "type": "array",
      "description": "Generated invoices with complete audit trail",
      "items": {
        "$ref": "#/$defs/invoice"
      }
    },
    "payments": {
      "type": "array",
      "description": "Payment records and transaction history",
      "items": {
        "$ref": "#/$defs/payment"
      }
    },
    "billing_adjustments": {
      "type": "array",
      "description": "Manual billing adjustments, credits, and refunds",
      "items": {
        "$ref": "#/$defs/billing_adjustment"
      }
    },
    "audit_trail": {
      "type": "array",
      "description": "Immutable audit log for all billing-related changes",
      "items": {
        "$ref": "#/$defs/audit_entry"
      }
    },
    "account_balance_transactions": {
      "type": "array",
      "description": "Immutable transaction events for account balance changes",
      "items": {
        "$ref": "#/$defs/balance_transaction"
      }
    },
    "plan_version_history": {
      "type": "array",
      "description": "Historical record of plan versions and transitions",
      "items": {
        "$ref": "#/$defs/plan_version_history"
      }
    }
  },
  "required": ["tenants", "billing_accounts", "subscription_plans"],
  "$defs": {
    "tenant": {
      "type": "object",
      "description": "Customer organization with complete isolation boundary (TMF SID Party/Customer role)",
      "properties": {
        "tenant_id": {
          "type": "string",
          "format": "uuid",
          "description": "Primary component of composite tenant-scoped keys"
        },
        "internal_id": {
          "type": "string",
          "format": "uuid",
          "description": "Internal entity identifier"
        },
        "organization_name": {
          "type": "string",
          "minLength": 1,
          "maxLength": 255,
          "description": "Legal organization name"
        },
        "billing_contact": {
          "$ref": "#/$defs/contact_info"
        },
        "tenant_status": {
          "type": "string",
          "enum": ["active", "suspended", "cancelled", "trial"],
          "description": "Current tenant operational status"
        },
        "data_residency": {
          "type": "string",
          "enum": ["US", "EU", "APAC", "CA", "UK"],
          "description": "Data residency requirement for compliance"
        },
        "data_classification": {
          "type": "string",
          "enum": ["public", "internal", "confidential", "restricted"],
          "default": "confidential",
          "description": "Data sensitivity classification"
        },
        "encryption_required": {
          "type": "boolean",
          "default": true,
          "description": "Whether data requires encryption at rest"
        },
        "archive_status": {
          "type": "string",
          "enum": ["active", "archived", "purged"],
          "default": "active",
          "description": "Data lifecycle status"
        },
        "retention_period": {
          "type": "integer",
          "minimum": 0,
          "description": "Data retention period in days"
        },
        "archive_date": {
          "type": "string",
          "format": "date-time",
          "description": "When data was archived"
        },
        "partition_key": {
          "type": "string",
          "description": "Partitioning hint for tenant-based distribution"
        },
        "created_at": {
          "type": "string",
          "format": "date-time",
          "description": "Tenant creation timestamp"
        },
        "updated_at": {
          "type": "string",
          "format": "date-time",
          "description": "Last modification timestamp"
        },
        "tenant_metadata": {
          "type": "object",
          "additionalProperties": true,
          "description": "Flexible metadata for tenant-specific configurations"
        }
      },
      "required": ["tenant_id", "internal_id", "organization_name", "billing_contact", "tenant_status", "created_at"],
      "additionalProperties": false,
      "x-composite-key": "PRIMARY KEY (tenant_id, internal_id)",
      "x-tenant-isolation": "tenant_id MUST be first component of all keys, no global indexes without tenant_id prefix",
      "x-indexes": [
        "CREATE INDEX idx_tenant_status ON tenants(tenant_id, tenant_status)",
        "CREATE INDEX idx_tenant_created ON tenants(tenant_id, created_at)",
        "CREATE INDEX idx_tenant_residency ON tenants(tenant_id, data_residency)"
      ],
      "x-tenant-constraints": [
        "CONSTRAINT fk_tenant_isolation CHECK (tenant_id IS NOT NULL AND char_length(tenant_id) = 36)"
      ]
    },
    "billing_account": {
      "type": "object",
      "description": "Financial account for billing operations with complete transaction history",
      "properties": {
        "tenant_id": {
          "type": "string",
          "format": "uuid",
          "description": "Tenant isolation identifier (primary key component)"
        },
        "billing_account_id": {
          "type": "string",
          "format": "uuid",
          "description": "Account identifier (primary key component)"
        },
        "account_number": {
          "type": "string",
          "pattern": "^[A-Z0-9]{8,20}$",
          "description": "Human-readable account number"
        },
        "currency_code": {
          "type": "string",
          "pattern": "^[A-Z]{3}$",
          "description": "ISO 4217 currency code"
        },
        "payment_terms": {
          "type": "integer",
          "minimum": 0,
          "maximum": 365,
          "description": "Payment terms in days (e.g., Net 30)"
        },
        "credit_limit": {
          "$ref": "#/$defs/money_amount",
          "description": "Maximum credit allowance"
        },
        "payment_method": {
          "$ref": "#/$defs/payment_method"
        },
        "billing_address": {
          "$ref": "#/$defs/billing_address"
        },
        "tax_information": {
          "$ref": "#/$defs/tax_information"
        },
        "account_status": {
          "type": "string",
          "enum": ["active", "suspended", "closed", "collections"],
          "description": "Account status for payment processing"
        },
        "dunning_status": {
          "type": "string",
          "enum": ["current", "past_due", "failed_payment", "suspended"],
          "description": "Collections and dunning status"
        },
        "data_classification": {
          "type": "string",
          "enum": ["public", "internal", "confidential", "restricted"],
          "default": "confidential",
          "description": "Data sensitivity classification for financial data"
        },
        "encryption_required": {
          "type": "boolean",
          "default": true,
          "description": "Whether PII/financial data requires encryption at rest"
        },
        "archive_status": {
          "type": "string",
          "enum": ["active", "archived", "purged"],
          "default": "active",
          "description": "Data lifecycle status"
        },
        "retention_period": {
          "type": "integer",
          "minimum": 2555,
          "description": "Data retention period in days (minimum 7 years for financial records)"
        },
        "created_at": {
          "type": "string",
          "format": "date-time"
        },
        "updated_at": {
          "type": "string",
          "format": "date-time"
        }
      },
      "required": ["tenant_id", "billing_account_id", "account_number", "currency_code", "payment_terms", "account_status", "created_at"],
      "additionalProperties": false,
      "x-composite-key": "PRIMARY KEY (tenant_id, billing_account_id)",
      "x-tenant-isolation": "tenant_id required for all queries, enforced at index level",
      "x-foreign-keys": [
        "FOREIGN KEY (tenant_id) REFERENCES tenants(tenant_id) MATCH SIMPLE"
      ],
      "x-indexes": [
        "CREATE INDEX idx_account_status ON billing_accounts(tenant_id, account_status)",
        "CREATE INDEX idx_account_dunning ON billing_accounts(tenant_id, dunning_status)"
      ]
    },
    "subscription_plan": {
      "type": "object",
      "description": "Product offering with multi-dimensional pricing (TMF SID ProductOffering)",
      "properties": {
        "tenant_id": {
          "type": "string",
          "format": "uuid",
          "description": "Tenant scoping (for multi-tenant plans)"
        },
        "plan_id": {
          "type": "string",
          "format": "uuid",
          "description": "Plan identifier (primary key component)"
        },
        "plan_name": {
          "type": "string",
          "minLength": 1,
          "maxLength": 255,
          "description": "Human-readable plan name"
        },
        "plan_code": {
          "type": "string",
          "pattern": "^[A-Za-z0-9_-]{2,50}$",
          "description": "Unique plan code for API integration"
        },
        "plan_version": {
          "type": "string",
          "pattern": "^\\d+\\.\\d+\\.\\d+$",
          "description": "Semantic version for plan changes"
        },
        "plan_type": {
          "type": "string",
          "enum": ["seat_based", "usage_based", "hybrid", "flat_rate", "volume_tier"],
          "description": "Primary billing model type with polymorphic pricing support"
        },
        "billing_frequency": {
          "type": "string",
          "enum": ["monthly", "quarterly", "annual", "usage_based"],
          "description": "Billing cycle frequency"
        },
        "base_price": {
          "$ref": "#/$defs/money_amount",
          "description": "Base subscription price (for seat-based or flat rate)"
        },
        "seat_pricing": {
          "$ref": "#/$defs/seat_pricing_config",
          "description": "Seat-based pricing configuration"
        },
        "usage_pricing": {
          "type": "array",
          "description": "Usage-based pricing tiers and rates",
          "items": {
            "$ref": "#/$defs/usage_pricing_tier"
          }
        },
        "included_usage": {
          "type": "object",
          "description": "Usage included in base price",
          "additionalProperties": {
            "type": "number",
            "minimum": 0
          }
        },
        "pricing_rule_metadata": {
          "$ref": "#/$defs/pricing_rule_metadata",
          "description": "Configuration-driven pricing calculation rules with polymorphic engine support"
        },
        "tier_calculation_rules": {
          "type": "array",
          "description": "Data-driven tier processing configuration for flexible boundary management",
          "items": {
            "$ref": "#/$defs/tier_calculation_rule"
          }
        },
        "plan_features": {
          "type": "array",
          "description": "Available features and limits",
          "items": {
            "$ref": "#/$defs/plan_feature"
          }
        },
        "proration_config": {
          "$ref": "#/$defs/proration_config",
          "description": "Mid-cycle change proration calculation metadata"
        },
        "trial_period_days": {
          "type": "integer",
          "minimum": 0,
          "maximum": 365,
          "description": "Free trial period in days"
        },
        "setup_fee": {
          "$ref": "#/$defs/money_amount",
          "description": "One-time setup fee"
        },
        "plan_status": {
          "type": "string",
          "enum": ["active", "deprecated", "draft"],
          "description": "Plan availability status"
        },
        "effective_date": {
          "type": "string",
          "format": "date",
          "description": "Plan effective start date for versioning"
        },
        "end_date": {
          "type": "string",
          "format": "date",
          "description": "Plan deprecation date (if applicable)"
        },
        "archive_status": {
          "type": "string",
          "enum": ["active", "archived", "purged"],
          "default": "active",
          "description": "Data lifecycle status"
        },
        "retention_period": {
          "type": "integer",
          "minimum": 2555,
          "description": "Data retention period in days"
        },
        "created_at": {
          "type": "string",
          "format": "date-time"
        },
        "updated_at": {
          "type": "string",
          "format": "date-time"
        }
      },
      "required": ["plan_id", "plan_name", "plan_code", "plan_version", "plan_type", "billing_frequency", "plan_status", "effective_date", "created_at"],
      "additionalProperties": false,
      "x-composite-key": "PRIMARY KEY (plan_id)",
      "x-indexes": [
        "CREATE INDEX idx_plan_status ON subscription_plans(plan_status, effective_date)",
        "CREATE INDEX idx_plan_version ON subscription_plans(plan_id, plan_version)"
      ]
    },
    "subscription": {
      "type": "object",
      "description": "Customer subscription with complete lifecycle tracking (TMF SID ProductOrderItem)",
      "properties": {
        "tenant_id": {
          "type": "string",
          "format": "uuid",
          "description": "Tenant isolation identifier (primary key component)"
        },
        "subscription_id": {
          "type": "string",
          "format": "uuid",
          "description": "Subscription identifier (primary key component)"
        },
        "billing_account_id": {
          "type": "string",
          "format": "uuid",
          "description": "Associated billing account"
        },
        "plan_id": {
          "type": "string",
          "format": "uuid",
          "description": "Current subscription plan"
        },
        "subscription_number": {
          "type": "string",
          "pattern": "^SUB-[A-Z0-9]{8,20}$",
          "description": "Human-readable subscription number"
        },
        "subscription_status": {
          "type": "string",
          "enum": ["active", "trial", "past_due", "cancelled", "suspended", "pending"],
          "description": "Current subscription status"
        },
        "seat_count": {
          "type": "integer",
          "minimum": 0,
          "description": "Current number of seats (for seat-based plans)"
        },
        "seat_history": {
          "type": "array",
          "description": "Historical seat count changes for accurate proration",
          "items": {
            "$ref": "#/$defs/seat_change_event"
          }
        },
        "start_date": {
          "type": "string",
          "format": "date",
          "description": "Subscription start date"
        },
        "end_date": {
          "type": "string",
          "format": "date",
          "description": "Subscription end date (if applicable)"
        },
        "current_period_start": {
          "type": "string",
          "format": "date",
          "description": "Current billing period start"
        },
        "current_period_end": {
          "type": "string",
          "format": "date",
          "description": "Current billing period end"
        },
        "next_billing_date": {
          "type": "string",
          "format": "date",
          "description": "Next scheduled billing date"
        },
        "trial_end_date": {
          "type": "string",
          "format": "date",
          "description": "Trial period end date"
        },
        "cancellation_date": {
          "type": "string",
          "format": "date",
          "description": "Cancellation effective date"
        },
        "cancellation_reason": {
          "type": "string",
          "enum": ["customer_request", "payment_failure", "breach_of_terms", "downgrade"],
          "description": "Reason for cancellation"
        },
        "auto_renew": {
          "type": "boolean",
          "default": true,
          "description": "Automatic renewal flag"
        },
        "proration_behavior": {
          "type": "string",
          "enum": ["immediate", "next_cycle", "none"],
          "default": "immediate",
          "description": "How to handle mid-cycle changes"
        },
        "custom_pricing": {
          "type": "array",
          "description": "Customer-specific pricing overrides",
          "items": {
            "$ref": "#/$defs/custom_price_override"
          }
        },
        "archive_status": {
          "type": "string",
          "enum": ["active", "archived", "purged"],
          "default": "active",
          "description": "Data lifecycle status"
        },
        "retention_period": {
          "type": "integer",
          "minimum": 2555,
          "description": "Data retention period in days"
        },
        "subscription_metadata": {
          "type": "object",
          "additionalProperties": true,
          "description": "Custom subscription metadata"
        },
        "created_at": {
          "type": "string",
          "format": "date-time"
        },
        "updated_at": {
          "type": "string",
          "format": "date-time"
        }
      },
      "required": ["tenant_id", "subscription_id", "billing_account_id", "plan_id", "subscription_number", "subscription_status", "start_date", "current_period_start", "current_period_end", "auto_renew", "created_at"],
      "additionalProperties": false,
      "x-composite-key": "PRIMARY KEY (tenant_id, subscription_id)",
      "x-tenant-isolation": "All subscription queries MUST include tenant_id filter for performance and isolation",
      "x-foreign-keys": [
        "FOREIGN KEY (tenant_id, billing_account_id) REFERENCES billing_accounts(tenant_id, billing_account_id) MATCH SIMPLE",
        "FOREIGN KEY (plan_id) REFERENCES subscription_plans(plan_id) MATCH SIMPLE"
      ],
      "x-indexes": [
        "CREATE INDEX idx_subscription_billing ON subscriptions(tenant_id, current_period_start, subscription_status)",
        "CREATE INDEX idx_subscription_account ON subscriptions(tenant_id, billing_account_id)",
        "CREATE INDEX idx_subscription_renewal ON subscriptions(tenant_id, next_billing_date)"
      ]
    },
    "usage_event": {
      "type": "object",
      "description": "Individual usage event for metered billing with complete traceability (TMF SID UsageEvent)",
      "properties": {
        "tenant_id": {
          "type": "string",
          "format": "uuid",
          "description": "Tenant isolation identifier (primary key component)"
        },
        "event_id": {
          "type": "string",
          "format": "uuid",
          "description": "Event identifier (primary key component)"
        },
        "subscription_id": {
          "type": "string",
          "format": "uuid",
          "description": "Associated subscription"
        },
        "idempotency_key": {
          "type": "string",
          "minLength": 1,
          "maxLength": 255,
          "description": "Client-provided idempotency key for deduplication"
        },
        "meter_name": {
          "type": "string",
          "pattern": "^[a-z][a-z0-9_]*$",
          "description": "Usage meter identifier (e.g., api_calls, storage_gb)"
        },
        "event_type": {
          "type": "string",
          "description": "Specific event type for granular tracking"
        },
        "quantity": {
          "type": "number",
          "multipleOf": 0.000001,
          "minimum": 0,
          "description": "Usage quantity with high precision"
        },
        "unit": {
          "type": "string",
          "description": "Unit of measurement (calls, GB, hours, tokens)"
        },
        "event_timestamp": {
          "type": "string",
          "format": "date-time",
          "description": "When the usage actually occurred"
        },
        "ingestion_timestamp": {
          "type": "string",
          "format": "date-time",
          "description": "When the event was received by billing system"
        },
        "properties": {
          "type": "object",
          "additionalProperties": true,
          "description": "Additional event properties for analysis and billing"
        },
        "user_id": {
          "type": "string",
          "description": "User who generated the usage (for attribution)"
        },
        "source_system": {
          "type": "string",
          "description": "System that generated the event"
        },
        "correlation_id": {
          "type": "string",
          "description": "Correlation ID for request tracing"
        },
        "processed": {
          "type": "boolean",
          "default": false,
          "description": "Whether event has been processed for billing"
        },
        "billing_period": {
          "type": "string",
          "format": "date",
          "description": "Billing period this usage applies to"
        },
        "partition_date": {
          "type": "string",
          "format": "date",
          "description": "Partition date for time-based distribution (YYYY-MM-DD)"
        },
        "rate_applied": {
          "$ref": "#/$defs/money_amount",
          "description": "Rate applied when billing (for audit trail)"
        },
        "amount_calculated": {
          "$ref": "#/$defs/money_amount",
          "description": "Calculated billing amount (for audit trail)"
        },
        "partition_key": {
          "type": "string",
          "description": "Time-based partition key for data distribution"
        },
        "archive_status": {
          "type": "string",
          "enum": ["active", "archived", "purged"],
          "default": "active",
          "description": "Data lifecycle status"
        },
        "retention_period": {
          "type": "integer",
          "minimum": 2555,
          "description": "Data retention period in days"
        },
        "created_at": {
          "type": "string",
          "format": "date-time"
        }
      },
      "required": ["tenant_id", "event_id", "subscription_id", "idempotency_key", "meter_name", "quantity", "unit", "event_timestamp", "ingestion_timestamp", "partition_date", "created_at"],
      "additionalProperties": false,
      "x-composite-key": "PRIMARY KEY (tenant_id, event_id)",
      "x-tenant-isolation": "tenant_id required for all time-series queries to prevent cross-tenant access",
      "x-foreign-keys": [
        "FOREIGN KEY (tenant_id, subscription_id) REFERENCES subscriptions(tenant_id, subscription_id) MATCH SIMPLE"
      ],
      "x-indexes": [
        "CREATE INDEX idx_usage_time_tenant ON usage_events(tenant_id, event_timestamp, meter_name)",
        "CREATE INDEX idx_usage_billing_period ON usage_events(tenant_id, billing_period, meter_name)",
        "CREATE INDEX idx_usage_subscription ON usage_events(tenant_id, subscription_id, event_timestamp)",
        "CREATE INDEX idx_usage_idempotency ON usage_events(idempotency_key)",
        "CREATE INDEX idx_usage_processed ON usage_events(tenant_id, processed, event_timestamp)",
        "CREATE INDEX idx_usage_partition_date ON usage_events(tenant_id, partition_date, meter_name)"
      ],
      "x-partitioning": {
        "strategy": "RANGE",
        "key": "partition_date",
        "interval": "1 MONTH",
        "tenant_distribution": "HASH(tenant_id)",
        "compression": "enabled",
        "retention_policy": "auto_purge_after_retention_period"
      }
    },
    "usage_aggregation": {
      "type": "object",
      "description": "Pre-computed usage aggregations for billing performance and accuracy",
      "properties": {
        "tenant_id": {
          "type": "string",
          "format": "uuid",
          "description": "Tenant isolation identifier (primary key component)"
        },
        "aggregation_id": {
          "type": "string",
          "format": "uuid",
          "description": "Aggregation identifier (primary key component)"
        },
        "subscription_id": {
          "type": "string",
          "format": "uuid",
          "description": "Associated subscription"
        },
        "meter_name": {
          "type": "string",
          "pattern": "^[a-z][a-z0-9_]*$",
          "description": "Usage meter identifier"
        },
        "period_start": {
          "type": "string",
          "format": "date-time",
          "description": "Aggregation period start"
        },
        "period_end": {
          "type": "string",
          "format": "date-time",
          "description": "Aggregation period end"
        },
        "aggregation_type": {
          "type": "string",
          "enum": ["sum", "count", "max", "min", "average", "distinct_count"],
          "description": "Aggregation method applied"
        },
        "total_quantity": {
          "type": "number",
          "multipleOf": 0.000001,
          "minimum": 0,
          "description": "Aggregated quantity"
        },
        "event_count": {
          "type": "integer",
          "minimum": 0,
          "description": "Number of events aggregated"
        },
        "billable_quantity": {
          "type": "number",
          "multipleOf": 0.000001,
          "minimum": 0,
          "description": "Quantity eligible for billing (after inclusions)"
        },
        "total_amount": {
          "$ref": "#/$defs/money_amount",
          "description": "Total calculated billing amount"
        },
        "tier_breakdown": {
          "type": "array",
          "description": "Breakdown by pricing tiers",
          "items": {
            "$ref": "#/$defs/usage_tier_calculation"
          }
        },
        "last_processed_event": {
          "type": "string",
          "format": "uuid",
          "description": "Last event included in aggregation"
        },
        "finalized": {
          "type": "boolean",
          "default": false,
          "description": "Whether aggregation is final for billing"
        },
        "partition_date": {
          "type": "string",
          "format": "date",
          "description": "Partition date for time-based distribution"
        },
        "partition_key": {
          "type": "string",
          "description": "Time-based partition key for data distribution"
        },
        "archive_status": {
          "type": "string",
          "enum": ["active", "archived", "purged"],
          "default": "active",
          "description": "Data lifecycle status"
        },
        "created_at": {
          "type": "string",
          "format": "date-time"
        },
        "updated_at": {
          "type": "string",
          "format": "date-time"
        }
      },
      "required": ["tenant_id", "aggregation_id", "subscription_id", "meter_name", "period_start", "period_end", "aggregation_type", "total_quantity", "event_count", "billable_quantity", "total_amount", "partition_date", "created_at"],
      "additionalProperties": false,
      "x-composite-key": "PRIMARY KEY (tenant_id, aggregation_id)",
      "x-tenant-isolation": "tenant_id enforced for all aggregation queries and temporal access patterns",
      "x-foreign-keys": [
        "FOREIGN KEY (tenant_id, subscription_id) REFERENCES subscriptions(tenant_id, subscription_id) MATCH SIMPLE"
      ],
      "x-indexes": [
        "CREATE INDEX idx_aggregation_billing ON usage_aggregations(tenant_id, meter_name, period_start)",
        "CREATE INDEX idx_aggregation_finalized ON usage_aggregations(tenant_id, finalized, period_start)",
        "CREATE INDEX idx_aggregation_partition ON usage_aggregations(tenant_id, partition_date, meter_name)"
      ],
      "x-partitioning": {
        "strategy": "RANGE",
        "key": "partition_date",
        "interval": "1 MONTH",
        "tenant_distribution": "HASH(tenant_id)"
      }
    },
    "invoice": {
      "type": "object",
      "description": "Complete invoice with line items and audit trail (TMF SID CustomerBill)",
      "properties": {
        "tenant_id": {
          "type": "string",
          "format": "uuid",
          "description": "Tenant isolation identifier (primary key component)"
        },
        "invoice_id": {
          "type": "string",
          "format": "uuid",
          "description": "Invoice identifier (primary key component)"
        },
        "billing_account_id": {
          "type": "string",
          "format": "uuid",
          "description": "Associated billing account"
        },
        "subscription_id": {
          "type": "string",
          "format": "uuid",
          "description": "Associated subscription"
        },
        "invoice_number": {
          "type": "string",
          "pattern": "^INV-[A-Z0-9]{8,20}$",
          "description": "Human-readable invoice number"
        },
        "invoice_status": {
          "type": "string",
          "enum": ["draft", "pending", "sent", "paid", "overdue", "cancelled", "refunded"],
          "description": "Current invoice status"
        },
        "invoice_type": {
          "type": "string",
          "enum": ["subscription", "usage", "one_time", "adjustment"],
          "description": "Type of invoice"
        },
        "billing_period_start": {
          "type": "string",
          "format": "date",
          "description": "Billing period start date"
        },
        "billing_period_end": {
          "type": "string",
          "format": "date",
          "description": "Billing period end date"
        },
        "issue_date": {
          "type": "string",
          "format": "date",
          "description": "Invoice issue date"
        },
        "due_date": {
          "type": "string",
          "format": "date",
          "description": "Payment due date"
        },
        "customer_snapshot": {
          "$ref": "#/$defs/customer_invoice_snapshot",
          "description": "Customer information at time of invoice generation"
        },
        "line_items": {
          "type": "array",
          "description": "Detailed invoice line items",
          "items": {
            "$ref": "#/$defs/invoice_line_item"
          }
        },
        "subtotal": {
          "$ref": "#/$defs/money_amount",
          "description": "Pre-tax total"
        },
        "tax_amount": {
          "$ref": "#/$defs/money_amount",
          "description": "Total tax amount"
        },
        "total_amount": {
          "$ref": "#/$defs/money_amount",
          "description": "Final invoice total"
        },
        "amount_paid": {
          "$ref": "#/$defs/money_amount",
          "description": "Amount already paid"
        },
        "amount_due": {
          "$ref": "#/$defs/money_amount",
          "description": "Outstanding amount"
        },
        "tax_breakdown": {
          "type": "array",
          "description": "Detailed tax calculations",
          "items": {
            "$ref": "#/$defs/tax_line_item"
          }
        },
        "discount_applied": {
          "$ref": "#/$defs/money_amount",
          "description": "Total discounts applied"
        },
        "payment_terms": {
          "type": "integer",
          "minimum": 0,
          "description": "Payment terms in days"
        },
        "notes": {
          "type": "string",
          "maxLength": 1000,
          "description": "Invoice notes"
        },
        "external_invoice_id": {
          "type": "string",
          "description": "External system invoice reference"
        },
        "archive_status": {
          "type": "string",
          "enum": ["active", "archived", "purged"],
          "default": "active",
          "description": "Data lifecycle status"
        },
        "retention_period": {
          "type": "integer",
          "minimum": 2555,
          "description": "Data retention period in days (minimum 7 years for financial records)"
        },
        "created_at": {
          "type": "string",
          "format": "date-time"
        },
        "updated_at": {
          "type": "string",
          "format": "date-time"
        },
        "finalized_at": {
          "type": "string",
          "format": "date-time",
          "description": "When invoice was finalized (immutable)"
        }
      },
      "required": ["tenant_id", "invoice_id", "billing_account_id", "subscription_id", "invoice_number", "invoice_status", "invoice_type", "billing_period_start", "billing_period_end", "issue_date", "due_date", "customer_snapshot", "line_items", "subtotal", "tax_amount", "total_amount", "amount_due", "created_at"],
      "additionalProperties": false,
      "x-composite-key": "PRIMARY KEY (tenant_id, invoice_id)",
      "x-tenant-isolation": "tenant_id enforced for all invoice operations and billing cycle queries",
      "x-foreign-keys": [
        "FOREIGN KEY (tenant_id, billing_account_id) REFERENCES billing_accounts(tenant_id, billing_account_id) MATCH SIMPLE",
        "FOREIGN KEY (tenant_id, subscription_id) REFERENCES subscriptions(tenant_id, subscription_id) MATCH SIMPLE"
      ],
      "x-indexes": [
        "CREATE INDEX idx_invoice_account ON invoices(tenant_id, billing_account_id, issue_date)",
        "CREATE INDEX idx_invoice_status ON invoices(tenant_id, invoice_status, due_date)",
        "CREATE INDEX idx_invoice_billing_period ON invoices(tenant_id, billing_period_start, billing_period_end)"
      ]
    },
    "payment": {
      "type": "object",
      "description": "Payment record with complete transaction details",
      "properties": {
        "tenant_id": {
          "type": "string",
          "format": "uuid",
          "description": "Tenant isolation identifier (primary key component)"
        },
        "payment_id": {
          "type": "string",
          "format": "uuid",
          "description": "Payment identifier (primary key component)"
        },
        "billing_account_id": {
          "type": "string",
          "format": "uuid",
          "description": "Associated billing account"
        },
        "invoice_id": {
          "type": "string",
          "format": "uuid",
          "description": "Associated invoice (if applicable)"
        },
        "payment_reference": {
          "type": "string",
          "pattern": "^PAY-[A-Z0-9]{8,20}$",
          "description": "Human-readable payment reference"
        },
        "payment_method_type": {
          "type": "string",
          "enum": ["credit_card", "bank_transfer", "ach", "wire", "check", "cash"],
          "description": "Payment method used"
        },
        "payment_status": {
          "type": "string",
          "enum": ["pending", "processing", "completed", "failed", "cancelled", "refunded"],
          "description": "Payment processing status"
        },
        "amount": {
          "$ref": "#/$defs/money_amount",
          "description": "Payment amount"
        },
        "fee_amount": {
          "$ref": "#/$defs/money_amount",
          "description": "Processing fees"
        },
        "net_amount": {
          "$ref": "#/$defs/money_amount",
          "description": "Net amount received"
        },
        "payment_date": {
          "type": "string",
          "format": "date-time",
          "description": "When payment was made"
        },
        "settled_date": {
          "type": "string",
          "format": "date-time",
          "description": "When payment settled"
        },
        "processor_transaction_id": {
          "type": "string",
          "description": "External payment processor transaction ID"
        },
        "failure_reason": {
          "type": "string",
          "description": "Reason for payment failure"
        },
        "refund_amount": {
          "$ref": "#/$defs/money_amount",
          "description": "Amount refunded (if applicable)"
        },
        "notes": {
          "type": "string",
          "maxLength": 500,
          "description": "Payment notes"
        },
        "data_classification": {
          "type": "string",
          "enum": ["public", "internal", "confidential", "restricted"],
          "default": "restricted",
          "description": "Data sensitivity classification for PCI compliance"
        },
        "encryption_required": {
          "type": "boolean",
          "default": true,
          "description": "Whether payment data requires encryption at rest"
        },
        "archive_status": {
          "type": "string",
          "enum": ["active", "archived", "purged"],
          "default": "active",
          "description": "Data lifecycle status"
        },
        "retention_period": {
          "type": "integer",
          "minimum": 2555,
          "description": "Data retention period in days"
        },
        "created_at": {
          "type": "string",
          "format": "date-time"
        },
        "updated_at": {
          "type": "string",
          "format": "date-time"
        }
      },
      "required": ["tenant_id", "payment_id", "billing_account_id", "payment_reference", "payment_method_type", "payment_status", "amount", "net_amount", "payment_date", "created_at"],
      "additionalProperties": false,
      "x-composite-key": "PRIMARY KEY (tenant_id, payment_id)",
      "x-tenant-isolation": "tenant_id enforced for all payment operations and account reconciliation",
      "x-foreign-keys": [
        "FOREIGN KEY (tenant_id, billing_account_id) REFERENCES billing_accounts(tenant_id, billing_account_id) MATCH SIMPLE",
        "FOREIGN KEY (tenant_id, invoice_id) REFERENCES invoices(tenant_id, invoice_id) MATCH SIMPLE"
      ],
      "x-indexes": [
        "CREATE INDEX idx_payment_account ON payments(tenant_id, billing_account_id, payment_date)",
        "CREATE INDEX idx_payment_status ON payments(tenant_id, payment_status, payment_date)"
      ]
    },
    "billing_adjustment": {
      "type": "object",
      "description": "Manual billing adjustments with audit trail",
      "properties": {
        "tenant_id": {
          "type": "string",
          "format": "uuid",
          "description": "Tenant isolation identifier (primary key component)"
        },
        "adjustment_id": {
          "type": "string",
          "format": "uuid",
          "description": "Adjustment identifier (primary key component)"
        },
        "billing_account_id": {
          "type": "string",
          "format": "uuid",
          "description": "Associated billing account"
        },
        "adjustment_type": {
          "type": "string",
          "enum": ["credit", "debit", "refund", "write_off", "discount"],
          "description": "Type of adjustment"
        },
        "amount": {
          "$ref": "#/$defs/money_amount",
          "description": "Adjustment amount"
        },
        "reason": {
          "type": "string",
          "enum": ["billing_error", "service_credit", "goodwill", "dispute_resolution", "contract_adjustment"],
          "description": "Reason for adjustment"
        },
        "description": {
          "type": "string",
          "maxLength": 500,
          "description": "Detailed adjustment description"
        },
        "applied_to_invoice": {
          "type": "string",
          "format": "uuid",
          "description": "Invoice this adjustment applies to"
        },
        "authorized_by": {
          "type": "string",
          "description": "User who authorized the adjustment"
        },
        "effective_date": {
          "type": "string",
          "format": "date",
          "description": "Effective date of adjustment"
        },
        "reversal_of": {
          "type": "string",
          "format": "uuid",
          "description": "Original adjustment this reverses"
        },
        "archive_status": {
          "type": "string",
          "enum": ["active", "archived", "purged"],
          "default": "active",
          "description": "Data lifecycle status"
        },
        "retention_period": {
          "type": "integer",
          "minimum": 2555,
          "description": "Data retention period in days"
        },
        "created_at": {
          "type": "string",
          "format": "date-time"
        }
      },
      "required": ["tenant_id", "adjustment_id", "billing_account_id", "adjustment_type", "amount", "reason", "description", "authorized_by", "effective_date", "created_at"],
      "additionalProperties": false,
      "x-composite-key": "PRIMARY KEY (tenant_id, adjustment_id)",
      "x-tenant-isolation": "tenant_id enforced to prevent cross-tenant adjustment access",
      "x-foreign-keys": [
        "FOREIGN KEY (tenant_id, billing_account_id) REFERENCES billing_accounts(tenant_id, billing_account_id) MATCH SIMPLE"
      ],
      "x-indexes": [
        "CREATE INDEX idx_adjustment_account ON billing_adjustments(tenant_id, billing_account_id, effective_date)"
      ]
    },
    "audit_entry": {
      "type": "object",
      "description": "Immutable audit log entry for compliance and traceability capturing all billing CRUD operations",
      "properties": {
        "tenant_id": {
          "type": "string",
          "format": "uuid",
          "description": "Tenant isolation identifier (primary key component)"
        },
        "audit_id": {
          "type": "string",
          "format": "uuid",
          "description": "Audit entry identifier (primary key component)"
        },
        "entity_type": {
          "type": "string",
          "enum": ["subscription", "invoice", "payment", "adjustment", "usage_event", "plan", "tenant", "billing_account"],
          "description": "Type of entity being audited"
        },
        "entity_id": {
          "type": "string",
          "format": "uuid",
          "description": "ID of entity being audited"
        },
        "action": {
          "type": "string",
          "enum": ["created", "updated", "deleted", "processed", "finalized", "cancelled", "accessed"],
          "description": "Action performed including read operations for critical data"
        },
        "user_id": {
          "type": "string",
          "description": "User who performed the action"
        },
        "system_component": {
          "type": "string",
          "description": "System component that performed the action"
        },
        "before_state": {
          "type": "object",
          "additionalProperties": true,
          "description": "Entity state before change"
        },
        "after_state": {
          "type": "object",
          "additionalProperties": true,
          "description": "Entity state after change"
        },
        "changes": {
          "type": "object",
          "additionalProperties": true,
          "description": "Specific fields that changed"
        },
        "correlation
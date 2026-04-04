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
    }
  },
  "required": ["tenants", "billing_accounts", "subscription_plans"],
  "$defs": {
    "tenant": {
      "type": "object",
      "description": "Tenant organization with complete isolation boundary",
      "properties": {
        "tenant_id": {
          "type": "string",
          "format": "uuid",
          "description": "Unique tenant identifier for data isolation"
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
          "description": "Data residency requirement for compliance"
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
      "required": ["tenant_id", "organization_name", "billing_contact", "tenant_status", "created_at"],
      "additionalProperties": false
    },
    "billing_account": {
      "type": "object",
      "description": "Financial account for billing operations with complete transaction history",
      "properties": {
        "billing_account_id": {
          "type": "string",
          "format": "uuid",
          "description": "Unique billing account identifier"
        },
        "tenant_id": {
          "type": "string",
          "format": "uuid",
          "description": "Associated tenant identifier"
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
        "current_balance": {
          "$ref": "#/$defs/money_amount",
          "description": "Current account balance (negative = credit)"
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
        "created_at": {
          "type": "string",
          "format": "date-time"
        },
        "updated_at": {
          "type": "string",
          "format": "date-time"
        }
      },
      "required": ["billing_account_id", "tenant_id", "account_number", "currency_code", "payment_terms", "current_balance", "account_status", "created_at"],
      "additionalProperties": false
    },
    "subscription_plan": {
      "type": "object",
      "description": "Subscription plan definition with multi-dimensional pricing",
      "properties": {
        "plan_id": {
          "type": "string",
          "format": "uuid",
          "description": "Unique plan identifier"
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
        "plan_type": {
          "type": "string",
          "enum": ["seat_based", "usage_based", "hybrid", "flat_rate"],
          "description": "Primary billing model type"
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
        "plan_features": {
          "type": "array",
          "description": "Available features and limits",
          "items": {
            "$ref": "#/$defs/plan_feature"
          }
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
          "description": "Plan effective start date"
        },
        "end_date": {
          "type": "string",
          "format": "date",
          "description": "Plan deprecation date (if applicable)"
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
      "required": ["plan_id", "plan_name", "plan_code", "plan_type", "billing_frequency", "plan_status", "effective_date", "created_at"],
      "additionalProperties": false
    },
    "subscription": {
      "type": "object",
      "description": "Customer subscription with complete lifecycle tracking",
      "properties": {
        "subscription_id": {
          "type": "string",
          "format": "uuid",
          "description": "Unique subscription identifier"
        },
        "tenant_id": {
          "type": "string",
          "format": "uuid",
          "description": "Associated tenant"
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
      "required": ["subscription_id", "tenant_id", "billing_account_id", "plan_id", "subscription_number", "subscription_status", "start_date", "current_period_start", "current_period_end", "auto_renew", "created_at"],
      "additionalProperties": false
    },
    "usage_event": {
      "type": "object",
      "description": "Individual usage event for metered billing with complete traceability",
      "properties": {
        "event_id": {
          "type": "string",
          "format": "uuid",
          "description": "Unique event identifier"
        },
        "tenant_id": {
          "type": "string",
          "format": "uuid",
          "description": "Tenant isolation identifier"
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
        "rate_applied": {
          "$ref": "#/$defs/money_amount",
          "description": "Rate applied when billing (for audit trail)"
        },
        "amount_calculated": {
          "$ref": "#/$defs/money_amount",
          "description": "Calculated billing amount (for audit trail)"
        },
        "created_at": {
          "type": "string",
          "format": "date-time"
        }
      },
      "required": ["event_id", "tenant_id", "subscription_id", "idempotency_key", "meter_name", "quantity", "unit", "event_timestamp", "ingestion_timestamp", "created_at"],
      "additionalProperties": false
    },
    "usage_aggregation": {
      "type": "object",
      "description": "Pre-computed usage aggregations for billing performance and accuracy",
      "properties": {
        "aggregation_id": {
          "type": "string",
          "format": "uuid",
          "description": "Unique aggregation identifier"
        },
        "tenant_id": {
          "type": "string",
          "format": "uuid",
          "description": "Tenant isolation identifier"
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
        "created_at": {
          "type": "string",
          "format": "date-time"
        },
        "updated_at": {
          "type": "string",
          "format": "date-time"
        }
      },
      "required": ["aggregation_id", "tenant_id", "subscription_id", "meter_name", "period_start", "period_end", "aggregation_type", "total_quantity", "event_count", "billable_quantity", "total_amount", "created_at"],
      "additionalProperties": false
    },
    "invoice": {
      "type": "object",
      "description": "Complete invoice with line items and audit trail",
      "properties": {
        "invoice_id": {
          "type": "string",
          "format": "uuid",
          "description": "Unique invoice identifier"
        },
        "tenant_id": {
          "type": "string",
          "format": "uuid",
          "description": "Tenant isolation identifier"
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
      "required": ["invoice_id", "tenant_id", "billing_account_id", "subscription_id", "invoice_number", "invoice_status", "invoice_type", "billing_period_start", "billing_period_end", "issue_date", "due_date", "customer_snapshot", "line_items", "subtotal", "tax_amount", "total_amount", "amount_due", "created_at"],
      "additionalProperties": false
    },
    "payment": {
      "type": "object",
      "description": "Payment record with complete transaction details",
      "properties": {
        "payment_id": {
          "type": "string",
          "format": "uuid",
          "description": "Unique payment identifier"
        },
        "tenant_id": {
          "type": "string",
          "format": "uuid",
          "description": "Tenant isolation identifier"
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
        "created_at": {
          "type": "string",
          "format": "date-time"
        },
        "updated_at": {
          "type": "string",
          "format": "date-time"
        }
      },
      "required": ["payment_id", "tenant_id", "billing_account_id", "payment_reference", "payment_method_type", "payment_status", "amount", "net_amount", "payment_date", "created_at"],
      "additionalProperties": false
    },
    "billing_adjustment": {
      "type": "object",
      "description": "Manual billing adjustments with audit trail",
      "properties": {
        "adjustment_id": {
          "type": "string",
          "format": "uuid",
          "description": "Unique adjustment identifier"
        },
        "tenant_id": {
          "type": "string",
          "format": "uuid",
          "description": "Tenant isolation identifier"
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
        "created_at": {
          "type": "string",
          "format": "date-time"
        }
      },
      "required": ["adjustment_id", "tenant_id", "billing_account_id", "adjustment_type", "amount", "reason", "description", "authorized_by", "effective_date", "created_at"],
      "additionalProperties": false
    },
    "audit_entry": {
      "type": "object",
      "description": "Immutable audit log entry for compliance and traceability",
      "properties": {
        "audit_id": {
          "type": "string",
          "format": "uuid",
          "description": "Unique audit entry identifier"
        },
        "tenant_id": {
          "type": "string",
          "format": "uuid",
          "description": "Tenant isolation identifier"
        },
        "entity_type": {
          "type": "string",
          "enum": ["subscription", "invoice", "payment", "adjustment", "usage_event", "plan"],
          "description": "Type of entity being audited"
        },
        "entity_id": {
          "type": "string",
          "format": "uuid",
          "description": "ID of entity being audited"
        },
        "action": {
          "type": "string",
          "enum": ["created", "updated", "deleted", "processed", "finalized", "cancelled"],
          "description": "Action performed"
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
        "correlation_id": {
          "type": "string",
          "description": "Request correlation ID"
        },
        "ip_address": {
          "type": "string",
          "format": "ipv4",
          "description": "Source IP address"
        },
        "user_agent": {
          "type": "string",
          "description": "User agent string"
        },
        "timestamp": {
          "type": "string",
          "format": "date-time",
          "description": "Audit event timestamp"
        }
      },
      "required": ["audit_id", "tenant_id", "entity_type", "entity_id", "action", "timestamp"],
      "additionalProperties": false
    },
    "money_amount": {
      "type": "object",
      "description": "Precise monetary amount with currency",
      "properties": {
        "amount": {
          "type": "integer",
          "description": "Amount in smallest currency unit (e.g., cents)"
        },
        "currency": {
          "type": "string",
          "pattern": "^[A-Z]{3}$",
          "description": "ISO 4217 currency code"
        }
      },
      "required": ["amount", "currency"],
      "additionalProperties": false
    },
    "contact_info": {
      "type": "object",
      "description": "Contact information",
      "properties": {
        "name": {
          "type": "string",
          "minLength": 1,
          "maxLength": 255
        },
        "email": {
          "type": "string",
          "format": "email"
        },
        "phone": {
          "type": "string",
          "pattern": "^\\+?[1-9]\\d{1,14}$"
        }
      },
      "required": ["name", "email"],
      "additionalProperties": false
    },
    "seat_pricing_config": {
      "type": "object",
      "description": "Seat-based pricing configuration",
      "properties": {
        "per_seat_price": {
          "$ref": "#/$defs/money_amount",
          "description": "Price per seat"
        },
        "minimum_seats": {
          "type": "integer",
          "minimum": 1,
          "description": "Minimum required seats"
        },
        "maximum_seats": {
          "type": "integer",
          "minimum": 1,
          "description": "Maximum allowed seats"
        },
        "volume_discounts": {
          "type": "array",
          "description": "Volume-based discounts",
          "items": {
            "$ref": "#/$defs/volume_discount_tier"
          }
        },
        "proration_policy": {
          "type": "string",
          "enum": ["immediate", "next_cycle", "none"],
          "description": "How seat changes are handled"
        }
      },
      "required": ["per_seat_price", "minimum_seats"],
      "additionalProperties": false
    },
    "usage_pricing_tier": {
      "type": "object",
      "description": "Usage-based pricing tier",
      "properties": {
        "meter_name": {
          "type": "string",
          "pattern": "^[a-z][a-z0-9_]*$",
          "description": "Usage meter identifier"
        },
        "pricing_model": {
          "type": "string",
          "enum": ["per_unit", "tiered", "volume", "package"],
          "description": "Pricing model type"
        },
        "unit_price": {
          "$ref": "#/$defs/money_amount",
          "description": "Price per unit"
        },
        "tiers": {
          "type": "array",
          "description": "Pricing tiers for tiered/volume pricing",
          "items": {
            "$ref": "#/$defs/pricing_tier"
          }
        },
        "included_quantity": {
          "type": "number",
          "minimum": 0,
          "description": "Included usage in plan"
        },
        "overage_price": {
          "$ref": "#/$defs/money_amount",
          "description": "Price for usage over included amount"
        }
      },
      "required": ["meter_name", "pricing_model"],
      "additionalProperties": false
    },
    "pricing_tier": {
      "type": "object",
      "description": "Individual pricing tier",
      "properties": {
        "up_to": {
          "type": "number",
          "minimum": 0,
          "description": "Upper bound of tier (null for unlimited)"
        },
        "unit_price": {
          "$ref": "#/$defs/money_amount",
          "description": "Price per unit in this tier"
        },
        "flat_fee": {
          "$ref": "#/$defs/money_amount",
          "description": "Flat fee for this tier"
        }
      },
      "required": ["unit_price"],
      "additionalProperties": false
    },
    "volume_discount_tier": {
      "type": "object",
      "description": "Volume discount tier",
      "properties": {
        "min_seats": {
          "type": "integer",
          "minimum": 1,
          "description": "Minimum seats for discount"
        },
        "discount_percentage": {
          "type": "number",
          "minimum": 0,
          "maximum": 100,
          "description": "Discount percentage"
        }
      },
      "required": ["min_seats", "discount_percentage"],
      "additionalProperties": false
    },
    "plan_feature": {
      "type": "object",
      "description": "Plan feature definition",
      "properties": {
        "feature_code": {
          "type": "string",
          "pattern": "^[a-z][a-z0-9_]*$",
          "description": "Feature identifier"
        },
        "feature_name": {
          "type": "string",
          "description": "Human-readable feature name"
        },
        "enabled": {
          "type": "boolean",
          "description": "Whether feature is enabled"
        },
        "limit": {
          "type": "number",
          "minimum": 0,
          "description": "Feature usage limit"
        }
      },
      "required": ["feature_code", "feature_name", "enabled"],
      "additionalProperties": false
    },
    "seat_change_event": {
      "type": "object",
      "description": "Seat count change event for proration calculations",
      "properties": {
        "change_id": {
          "type": "string",
          "format": "uuid"
        },
        "previous_seat_count": {
          "type": "integer",
          "minimum": 0"
        },
        "new_seat_count": {
          "type": "integer",
          "minimum": 0"
        },
        "effective_date": {
          "type": "string",
          "format": "date-time"
        },
        "change_reason": {
          "type": "string",
          "enum": ["upgrade", "downgrade", "correction"]
        },
        "proration_amount": {
          "$ref": "#/$defs/money_amount",
          "description": "Calculated proration amount"
        }
      },
      "required": ["change_id", "previous_seat_count", "new_seat_count", "effective_date", "change_reason"],
      "additionalProperties": false
    },
    "custom_price_override": {
      "type": "object",
      "description": "Customer-specific pricing override",
      "properties": {
        "override_id": {
          "type": "string",
          "format": "uuid"
        },
        "meter_name": {
          "type": "string",
          "pattern": "^[a-z][a-z0-9_]*$"
        },
        "custom_price": {
          "$ref": "#/$defs/money_amount"
        },
        "effective_date": {
          "type": "string",
          "format": "date"
        },
        "end_date": {
          "type": "string",
          "format": "date"
        }
      },
      "required": ["override_id", "meter_name", "custom_price", "effective_date"],
      "additionalProperties": false
    },
    "usage_tier_calculation": {
      "type": "object",
      "description": "Usage calculation breakdown by tier",
      "properties": {
        "tier_index": {
          "type": "integer",
          "minimum": 0"
        },
        "quantity_in_tier": {
          "type": "number",
          "minimum": 0"
        },
        "unit_price": {
          "$ref": "#/$defs/money_amount"
        },
        "tier_amount": {
          "$ref": "#/$defs/money_amount"
        }
      },
      "required": ["tier_index", "quantity_in_tier", "unit_price", "tier_amount"],
      "additionalProperties": false
    },
    "customer_invoice_snapshot": {
      "type": "object",
      "description": "Customer information at time of invoice generation",
      "properties": {
        "organization_name": {
          "type": "string"
        },
        "billing_contact": {
          "$ref": "#/$defs/contact_info"
        },
        "billing_address": {
          "$ref": "#/$defs/billing_address"
        },
        "tax_information": {
          "$ref": "#/$defs/tax_information"
        }
      },
      "required": ["organization_name", "billing_contact"],
      "additionalProperties": false
    },
    "invoice_line_item": {
      "type": "object",
      "description": "Detailed invoice line item",
      "properties": {
        "line_item_id": {
          "type": "string",
          "format": "uuid"
        },
        "description": {
          "type": "string",
          "maxLength": 500"
        },
        "item_type": {
          "type": "string",
          "enum": ["subscription", "usage", "setup_fee", "adjustment", "tax"]
        },
        "quantity": {
          "type": "number",
          "minimum": 0"
        },
        "unit_price": {
          "$ref": "#/$defs/money_amount"
        },
        "total_amount": {
          "$ref": "#/$defs/money_amount"
        },
        "period_start": {
          "type": "string",
          "format": "date"
        },
        "period_end": {
          "type": "string",
          "format": "date"
        },
        "meter_name": {
          "type": "string",
          "description": "Usage meter (for usage line items)"
        },
        "proration_details": {
          "$ref": "#/$defs/proration_details"
        }
      },
      "required": ["line_item_id", "description", "item_type", "quantity", "unit_price", "total_amount"],
      "additionalProperties": false
    },
    "tax_line_item": {
      "type": "object",
      "description": "Tax calculation line item",
      "properties": {
        "tax_name": {
          "type": "string"
        },
        "tax_rate": {
          "type": "number",
          "minimum": 0,
          "maximum": 1"
        },
        "taxable_amount": {
          "$ref": "#/$defs/money_amount"
        },
        "tax_amount": {
          "$ref": "#/$defs/money_amount"
        },
        "jurisdiction": {
          "type": "string"
        }
      },
      "required": ["tax_name", "tax_rate", "taxable_amount", "tax_amount"],
      "additionalProperties": false
    },
    "proration_details": {
      "type": "object",
      "description": "Proration calculation details",
      "properties": {
        "is_prorated": {
          "type": "boolean"
        },
        "proration_start": {
          "type": "string",
          "format": "date"
        },
        "proration_end": {
          "type": "string",
          "format": "date"
        },
        "days_in_period": {
          "type": "integer",
          "minimum": 1"
        },
        "prorated_days": {
          "type": "integer",
          "minimum": 0"
        }
      },
      "additionalProperties": false
    },
    "payment_method": {
      "type": "object",
      "description": "Payment method information",
      "properties": {
        "method_type": {
          "type": "string",
          "enum": ["credit_card", "bank_account", "ach", "wire"]
        },
        "last_four": {
          "type": "string",
          "pattern": "^\\d{4}$"
        },
        "expiry_date": {
          "type": "string",
          "pattern": "^\\d{2}/\\d{2}$"
        },
        "processor_token": {
          "type": "string",
          "description": "Tokenized payment method reference"
        }
      },
      "required": ["method_type"],
      "additionalProperties": false
    },
    "billing_address": {
      "type": "object",
      "description": "Billing address",
      "properties": {
        "line1": {
          "type": "string",
          "maxLength": 255"
        },
        "line2": {
          "type": "string",
          "maxLength": 255"
        },
        "city": {
          "type": "string",
          "maxLength": 100"
        },
        "state": {
          "type": "string",
          "maxLength": 50"
        },
        "postal_code": {
          "type": "string",
          "maxLength": 20"
        },
        "country": {
          "type": "string",
          "pattern": "^[A-Z]{2}$",
          "description": "ISO 3166-1 alpha-2 country code"
        }
      },
      "required": ["line1", "
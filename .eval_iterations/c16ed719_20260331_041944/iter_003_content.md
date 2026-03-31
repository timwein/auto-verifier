```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "title": "Multi-Tenant SaaS Billing System Schema",
  "version": "1.0.0",
  "type": "object",
  "definitions": {
    "money": {
      "type": "object",
      "properties": {
        "amount": {
          "type": "integer",
          "description": "Amount in smallest currency unit (e.g., cents)",
          "minimum": 0
        },
        "currency": {
          "type": "string",
          "pattern": "^[A-Z]{3}$",
          "description": "Three-letter ISO currency code"
        }
      },
      "required": ["amount", "currency"],
      "additionalProperties": false
    },
    "metered_dimension": {
      "type": "object",
      "properties": {
        "id": {
          "type": "string",
          "pattern": "^[a-z0-9_]+$",
          "description": "Unique identifier for the metered dimension"
        },
        "name": {
          "type": "string",
          "minLength": 1,
          "description": "Human-readable name"
        },
        "unit": {
          "type": "string",
          "minLength": 1,
          "description": "Unit of measurement (e.g., 'requests', 'gb_hours', 'tokens')"
        },
        "aggregation_method": {
          "type": "string",
          "enum": ["sum", "max", "last_value", "count"],
          "default": "sum"
        },
        "tiers": {
          "type": "array",
          "items": {
            "type": "object",
            "properties": {
              "up_to": {
                "oneOf": [
                  { "type": "integer", "minimum": 1 },
                  { "type": "null" }
                ],
                "description": "Upper limit for this tier, null for infinity"
              },
              "per_unit_amount": {
                "$ref": "#/definitions/money"
              },
              "flat_amount": {
                "$ref": "#/definitions/money"
              }
            },
            "required": ["up_to"],
            "anyOf": [
              { "required": ["per_unit_amount"] },
              { "required": ["flat_amount"] }
            ],
            "additionalProperties": false
          },
          "minItems": 1
        }
      },
      "required": ["id", "name", "unit", "tiers"],
      "additionalProperties": false
    },
    "address": {
      "type": "object",
      "properties": {
        "line1": { "type": "string", "minLength": 1 },
        "line2": { "type": "string" },
        "city": { "type": "string", "minLength": 1 },
        "state": { "type": "string" },
        "postal_code": { "type": "string" },
        "country": {
          "type": "string",
          "pattern": "^[A-Z]{2}$",
          "description": "Two-letter ISO country code"
        }
      },
      "required": ["line1", "city", "country"],
      "additionalProperties": false
    },
    "webhook_configuration": {
      "type": "object",
      "description": 
Advanced extension point for webhook event subscriptions
,
      "properties": {
        "id": {
          "type": "string",
          "pattern": "^webhook_[a-zA-Z0-9]{16,}$"
        },
        "url": {
          "type": "string",
          "format": "uri",
          "description": 
"Webhook endpoint URL for real-time event delivery"

        },
        "event_types": {
          "type": "array",
          "items": {
            "type": "string",
            "enum": ["subscription.created", "subscription.updated", "subscription.canceled", "invoice.paid", "invoice.failed", "usage.recorded"]
          },
          "minItems": 1
        },
        "signature_secret": {
          "type": "string",
          "minLength": 16,
          "description": 
"HMAC signature secret for webhook validation and security"

        },
        "retry_policy": {
          "type": "object",
          "properties": {
            "max_attempts": {
              "type": "integer",
              "minimum": 1,
              "maximum": 10,
              "default": 3
            },
            "backoff_strategy": {
              "type": "string",
              "enum": ["linear", "exponential"],
              "default": "exponential"
            }
          },
          "additionalProperties": false
        },
        "is_active": { "type": "boolean", "default": true },
        "metadata": {
          "type": "object",
          "additionalProperties": true
        }
      },
      "required": ["id", "url", "event_types", "signature_secret"],
      "additionalProperties": false
    },
    "custom_field_definition": {
      "type": "object",
      "description": "Advanced extension point for tenant-specific custom fields",
      "properties": {
        "field_name": {
          "type": "string",
          "pattern": "^[a-zA-Z_][a-zA-Z0-9_]*$",
          "description": "Custom field identifier"
        },
        "field_type": {
          "type": "string",
          "enum": ["string", "number", "boolean", "date", "array", "object"]
        },
        "validation_rules": {
          "type": "object",
          "properties": {
            "required": { "type": "boolean", "default": false },
            "min_length": { "type": "integer", "minimum": 0 },
            "max_length": { "type": "integer", "minimum": 1 },
            "pattern": { "type": "string", "format": "regex" },
            "enum_values": {
              "type": "array",
              "items": { "type": "string" }
            }
          },
          "additionalProperties": false
        },
        "display_options": {
          "type": "object",
          "properties": {
            "label": { "type": "string", "minLength": 1 },
            "description": { "type": "string" },
            "position": { "type": "integer", "minimum": 0 }
          },
          "additionalProperties": false
        }
      },
      "required": ["field_name", "field_type"],
      "additionalProperties": false
    }
  },
  "properties": {
    "tenant": {
      "type": "object",
      "properties": {
        "id": {
          "type": "string",
          "pattern": "^tenant_[a-zA-Z0-9]{16,}$"
        },
        "name": {
          "type": "string",
          "minLength": 1
        },
        "slug": {
          "type": "string",
          "pattern": "^[a-z0-9-]+$",
          "description": "URL-safe identifier for subdomain routing"
        },
        "status": {
          "type": "string",
          "enum": ["active", "suspended", "terminated"]
        },
        "region": {
          "type": "string",
          "enum": ["us", "eu", "apac"],
          "description": "Data residency region"
        },
        "billing_address": {
          "$ref": "#/definitions/address"
        },
        "tax_ids": {
          "type": "array",
          "items": {
            "type": "object",
            "properties": {
              "type": {
                "type": "string",
                "enum": ["eu_vat", "us_ein", "ca_bn", "au_abn", "gb_vat"]
              },
              "value": { "type": "string", "minLength": 1 }
            },
            "required": ["type", "value"],
            "additionalProperties": false
          }
        },
        "webhook_configurations": {
          "type": "array",
          "items": {
            "$ref": "#/definitions/webhook_configuration"
          },
          "description": "Webhook endpoints for real-time event notifications"
        },
        "custom_field_definitions": {
          "type": "array",
          "items": {
            "$ref": "#/definitions/custom_field_definition"
          },
          "description": "Tenant-specific custom field schema definitions"
        },
        "metadata": {
          "type": "object",
          "additionalProperties": true
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
      "required": ["id", "name", "slug", "status", "region", "created_at"],
      "additionalProperties": false
    },
    "customer": {
      "type": "object",
      "properties": {
        "id": {
          "type": "string",
          "pattern": "^cus_[a-zA-Z0-9]{16,}$"
        },
        "tenant_id": {
          "type": "string",
          "pattern": "^tenant_[a-zA-Z0-9]{16,}$"
        },
        "email": {
          "type": "string",
          "format": "email"
        },
        "name": { "type": "string", "minLength": 1 },
        "billing_address": {
          "$ref": "#/definitions/address"
        },
        "payment_methods": {
          "type": "array",
          "items": {
            "type": "object",
            "properties": {
              "id": { "type": "string", "minLength": 1 },
              "type": {
                "type": "string",
                "enum": ["card", "bank_account", "wallet"]
              },
              "is_default": { "type": "boolean", "default": false }
            },
            "required": ["id", "type"],
            "additionalProperties": false
          }
        },
        "balance": {
          "$ref": "#/definitions/money"
        },
        "metadata": {
          "type": "object",
          "additionalProperties": true
        },
        "created_at": {
          "type": "string",
          "format": "date-time"
        }
      },
      "required": ["id", "tenant_id", "email", "created_at"],
      "additionalProperties": false
    },
    "plan": {
      "type": "object",
      "properties": {
        "id": {
          "type": "string",
          "pattern": "^plan_[a-zA-Z0-9]{16,}$"
        },
        "tenant_id": {
          "type": "string",
          "pattern": "^tenant_[a-zA-Z0-9]{16,}$"
        },
        "name": { "type": "string", "minLength": 1 },
        "description": { "type": "string" },
        "pricing_model": {
          "type": "object",
          "properties": {
            "type": {
              "type": "string",
              "enum": ["seat_based", "usage_based", "hybrid"]
            },
            "seat_price": {
              "$ref": "#/definitions/money",
              "description": "Price per seat for seat-based or hybrid models"
            },
            "included_seats": {
              "type": "integer",
              "minimum": 0,
              "description": "Number of seats included in base price"
            },
            "metered_dimensions": {
              "type": "array",
              "items": {
                "$ref": "#/definitions/metered_dimension"
              },
              "description": "Usage-based pricing dimensions"
            }
          },
          "required": ["type"],
          "allOf": [
            {
              "if": {
                "properties": { "type": { "const": "seat_based" } }
              },
              "then": {
                "required": ["seat_price"]
              }
            },
            {
              "if": {
                "properties": { "type": { "const": "usage_based" } }
              },
              "then": {
                "required": ["metered_dimensions"],
                "properties": {
                  "metered_dimensions": {
                    "minItems": 1
                  }
                }
              }
            },
            {
              "if": {
                "properties": { "type": { "const": "hybrid" } }
              },
              "then": {
                "required": ["seat_price", "metered_dimensions"],
                "properties": {
                  "metered_dimensions": {
                    "minItems": 1
                  }
                }
              }
            }
          ],
          "additionalProperties": false
        },
        "billing_interval": {
          "type": "string",
          "enum": ["monthly", "quarterly", "annually"]
        },
        "trial_period_days": {
          "type": "integer",
          "minimum": 0,
          "maximum": 365
        },
        "is_active": { "type": "boolean", "default": true },
        "metadata": {
          "type": "object",
          "additionalProperties": true
        },
        "created_at": {
          "type": "string",
          "format": "date-time"
        }
      },
      "required": ["id", "tenant_id", "name", "pricing_model", "billing_interval", "is_active", "created_at"],
      "additionalProperties": false
    },
    "subscription": {
      "type": "object",
      "properties": {
        "id": {
          "type": "string",
          "pattern": "^sub_[a-zA-Z0-9]{16,}$"
        },
        "tenant_id": {
          "type": "string",
          "pattern": "^tenant_[a-zA-Z0-9]{16,}$"
        },
        "customer_id": {
          "type": "string",
          "pattern": "^cus_[a-zA-Z0-9]{16,}$"
        },
        "plan_id": {
          "type": "string",
          "pattern": "^plan_[a-zA-Z0-9]{16,}$"
        },
        "status": {
          "type": "string",
          "enum": ["trialing", "active", "past_due", "canceled", "unpaid", "incomplete", "paused"]
        },
        "seats": {
          "type": "integer",
          "minimum": 0,
          "description": "Number of seats for seat-based billing"
        },
        "current_period_start": {
          "type": "string",
          "format": "date-time"
        },
        "current_period_end": {
          "type": "string",
          "format": "date-time"
        },
        "trial_start": {
          "type": "string",
          "format": "date-time"
        },
        "trial_end": {
          "type": "string",
          "format": "date-time"
        },
        "canceled_at": {
          "type": "string",
          "format": "date-time"
        },
        "ended_at": {
          "type": "string",
          "format": "date-time"
        },
        "paused_at": {
          "type": "string",
          "format": "date-time"
        },
        "proration_behavior": {
          "type": "string",
          "enum": ["create_prorations", "none", "always_invoice"],
          "default": "create_prorations"
        },
        "metadata": {
          "type": "object",
          "additionalProperties": true
        },
        "created_at": {
          "type": "string",
          "format": "date-time"
        }
      },
      "required": ["id", "tenant_id", "customer_id", "plan_id", "status", "current_period_start", "current_period_end", "created_at"],
      "additionalProperties": false
    },
    "subscription_change": {
      "type": "object",
      "properties": {
        "id": {
          "type": "string",
          "pattern": "^change_[a-zA-Z0-9]{16,}$"
        },
        "tenant_id": {
          "type": "string",
          "pattern": "^tenant_[a-zA-Z0-9]{16,}$"
        },
        "subscription_id": {
          "type": "string",
          "pattern": "^sub_[a-zA-Z0-9]{16,}$"
        },
        "change_type": {
          "type": "string",
          "enum": ["upgrade", "downgrade", "seat_change", "plan_change", "pause", "resume", "cancellation"]
        },
        "effective_date": {
          "type": "string",
          "format": "date-time"
        },
        "previous_plan_id": {
          "type": "string",
          "pattern": "^plan_[a-zA-Z0-9]{16,}$"
        },
        "new_plan_id": {
          "type": "string",
          "pattern": "^plan_[a-zA-Z0-9]{16,}$"
        },
        "previous_seats": {
          "type": "integer",
          "minimum": 0
        },
        "new_seats": {
          "type": "integer",
          "minimum": 0
        },
        "proration_amount": {
          "$ref": "#/definitions/money"
        },
        "metadata": {
          "type": "object",
          "additionalProperties": true
        },
        "created_at": {
          "type": "string",
          "format": "date-time"
        }
      },
      "required": ["id", "tenant_id", "subscription_id", "change_type", "effective_date", "created_at"],
      "additionalProperties": false
    },
    "usage_record": {
      "type": "object",
      "properties": {
        "id": {
          "type": "string",
          "pattern": "^usage_[a-zA-Z0-9]{16,}$"
        },
        "tenant_id": {
          "type": "string",
          "pattern": "^tenant_[a-zA-Z0-9]{16,}$"
        },
        "subscription_id": {
          "type": "string",
          "pattern": "^sub_[a-zA-Z0-9]{16,}$"
        },
        "dimension_id": {
          "type": "string",
          "pattern": "^[a-z0-9_]+$"
        },
        "quantity": {
          "type": "number",
          "minimum": 0
        },
        "timestamp": {
          "type": "string",
          "format": "date-time"
        },
        "dimensions": {
          "type": "object",
          "additionalProperties": true,
          "description": "Additional metadata dimensions for analytics and reporting"
        },
        "idempotency_key": {
          "type": "string",
          "minLength": 1,
          "description": "Ensures idempotent usage recording"
        }
      },
      "required": ["id", "tenant_id", "subscription_id", "dimension_id", "quantity", "timestamp"],
      "additionalProperties": false
    },
    "invoice": {
      "type": "object",
      "properties": {
        "id": {
          "type": "string",
          "pattern": "^in_[a-zA-Z0-9]{16,}$"
        },
        "tenant_id": {
          "type": "string",
          "pattern": "^tenant_[a-zA-Z0-9]{16,}$"
        },
        "customer_id": {
          "type": "string",
          "pattern": "^cus_[a-zA-Z0-9]{16,}$"
        },
        "subscription_id": {
          "type": "string",
          "pattern": "^sub_[a-zA-Z0-9]{16,}$"
        },
        "number": {
          "type": "string",
          "minLength": 1,
          "description": "Human-readable invoice number"
        },
        "status": {
          "type": "string",
          "enum": ["draft", "open", "paid", "void", "uncollectible"]
        },
        "subtotal": {
          "$ref": "#/definitions/money"
        },
        "tax": {
          "$ref": "#/definitions/money"
        },
        "total": {
          "$ref": "#/definitions/money"
        },
        "amount_paid": {
          "$ref": "#/definitions/money"
        },
        "amount_due": {
          "$ref": "#/definitions/money"
        },
        "line_items": {
          "type": "array",
          "items": {
            "type": "object",
            "properties": {
              "id": { "type": "string", "minLength": 1 },
              "type": {
                "type": "string",
                "enum": ["subscription", "usage", "proration", "discount", "tax"]
              },
              "description": { "type": "string", "minLength": 1 },
              "quantity": {
                "type": "number",
                "minimum": 0
              },
              "unit_amount": {
                "$ref": "#/definitions/money"
              },
              "amount": {
                "$ref": "#/definitions/money"
              },
              "period_start": {
                "type": "string",
                "format": "date-time"
              },
              "period_end": {
                "type": "string",
                "format": "date-time"
              },
              "proration": {
                "type": "boolean",
                "default": false
              },
              "metadata": {
                "type": "object",
                "additionalProperties": true
              }
            },
            "required": ["id", "type", "description", "amount"],
            "additionalProperties": false
          },
          "minItems": 1
        },
        "due_date": {
          "type": "string",
          "format": "date-time"
        },
        "paid_at": {
          "type": "string",
          "format": "date-time"
        },
        "period_start": {
          "type": "string",
          "format": "date-time"
        },
        "period_end": {
          "type": "string",
          "format": "date-time"
        },
        "collection_method": {
          "type": "string",
          "enum": ["charge_automatically", "send_invoice"],
          "default": "charge_automatically"
        },
        "hosted_invoice_url": {
          "type": "string",
          "format": "uri"
        },
        "invoice_pdf": {
          "type": "string",
          "format": "uri"
        },
        "metadata": {
          "type": "object",
          "additionalProperties": true
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
      "required": ["id", "tenant_id", "customer_id", "status", "subtotal", "total", "amount_due", "line_items", "created_at"],
      "additionalProperties": false
    },
    "payment": {
      "type": "object",
      "properties": {
        "id": {
          "type": "string",
          "pattern": "^pay_[a-zA-Z0-9]{16,}$"
        },
        "tenant_id": {
          "type": "string",
          "pattern": "^tenant_[a-zA-Z0-9]{16,}$"
        },
        "customer_id": {
          "type": "string",
          "pattern": "^cus_[a-zA-Z0-9]{16,}$"
        },
        "invoice_id": {
          "type": "string",
          "pattern": "^in_[a-zA-Z0-9]{16,}$"
        },
        "amount": {
          "$ref": "#/definitions/money"
        },
        "status": {
          "type": "string",
          "enum": ["pending", "succeeded", "failed", "canceled", "refunded"]
        },
        "payment_method": {
          "type": "object",
          "properties": {
            "id": { "type": "string", "minLength": 1 },
            "type": {
              "type": "string",
              "enum": ["card", "bank_account", "wallet"]
            }
          },
          "required": ["id", "type"],
          "additionalProperties": false
        },
        "failure_reason": { "type": "string" },
        "captured_at": {
          "type": "string",
          "format": "date-time"
        },
        "metadata": {
          "type": "object",
          "additionalProperties": true
        },
        "created_at": {
          "type": "string",
          "format": "date-time"
        }
      },
      "required": ["id", "tenant_id", "customer_id", "amount", "status", "payment_method", "created_at"],
      "additionalProperties": false
    },
    "credit": {
      "type": "object",
      "properties": {
        "id": {
          "type": "string",
          "pattern": "^credit_[a-zA-Z0-9]{16,}$"
        },
        "tenant_id": {
          "type": "string",
          "pattern": "^tenant_[a-zA-Z0-9]{16,}$"
        },
        "customer_id": {
          "type": "string",
          "pattern": "^cus_[a-zA-Z0-9]{16,}$"
        },
        "amount": {
          "$ref": "#/definitions/money"
        },
        "remaining_amount": {
          "$ref": "#/definitions/money"
        },
        "expires_at": {
          "type": "string",
          "format": "date-time"
        },
        "reason": {
          "type": "string",
          "enum": ["prepayment", "refund", "promotional", "adjustment"]
        },
        "metadata": {
          "type": "object",
          "additionalProperties": true
        },
        "created_at": {
          "type": "string",
          "format": "date-time"
        }
      },
      "required": ["id", "tenant_id", "customer_id", "amount", "remaining_amount", "reason", "created_at"],
      "additionalProperties": false
    },
    "discount": {
      "type": "object",
      "properties": {
        "id": {
          "type": "string",
          "pattern": "^discount_[a-zA-Z0-9]{16,}$"
        },
        "tenant_id": {
          "type": "string",
          "pattern": "^tenant_[a-zA-Z0-9]{16,}$"
        },
        "name": {
          "type": "string",
          "minLength": 1
        },
        "type": {
          "type": "string",
          "enum": ["percentage", "fixed_amount"]
        },
        "value": {
          "type": "number",
          "minimum": 0
        },
        "currency": {
          "type": "string",
          "pattern": "^[A-Z]{3}$"
        },
        "duration": {
          "type": "string",
          "enum": ["once", "repeating", "forever"]
        },
        "duration_in_months": {
          "type": "integer",
          "minimum": 1
        },
        "valid_until": {
          "type": "string",
          "format": "date-time"
        },
        "max_redemptions": {
          "type": "integer",
          "minimum": 1
        },
        "times_redeemed": {
          "type": "integer",
          "minimum": 0,
          "default": 0
        },
        "metadata": {
          "type": "object",
          "additionalProperties": true
        },
        "created_at": {
          "type": "string",
          "format": "date-time"
        }
      },
      "required": ["id", "tenant_id", "name", "type", "value", "duration", "created_at"],
      "allOf": [
        {
          "if": {
            "properties": { "type": { "const": "fixed_amount" } }
          },
          "then": {
            "required": ["currency"]
          }
        },
        {
          "if": {
            "properties": { "duration": { "const": "repeating" } }
          },
          "then": {
            "required": ["duration_in_months"]
          }
        }
      ],
      "additionalProperties": false
    }
  },
  "required": ["tenant", "customer", "plan", "subscription", "invoice"],
  "additionalProperties": false,
  "x-schema-versioning": {
    "description": 
"Schema versioning strategy following semantic versioning (MAJOR.MINOR.PATCH) to communicate changes effectively"
,
    "version_policy": {
      "major": 
"Breaking schema changes that prevent interaction with historical data (e.g., removing required fields, changing field types incompatibly)"
,
      "minor": 
"Schema changes that may prevent interaction with some historical data (e.g., adding required fields without defaults)"
,
      "patch": 
"Schema changes compatible with all historical data (e.g., adding optional fields, relaxing constraints)"

    },
    "migration_strategy": {
      "backward_compatibility": 
"New versions remain compatible with older versions using default values for new fields and avoiding removal of existing fields"
,
      "migration_paths": 
"Version-aware parsing with migration functions to transform older schema versions during reads/writes"
,
      "compatibility_matrix": [
        {
          "version": "1.0.0",
          "compatible_with": ["1.0.x"],
          "breaking_changes": []
        },
        {
          "version": "1.1.0",
          "compatible_with": ["1.0.x", "1.1.x"],
          "new_features": ["webhook_configuration", "custom_field_definition"]
        }
      ]
    },
    "evolution_guidelines": {
      "additive_changes": 
"New optional fields for backward compatibility, avoid removing/renaming fields - deprecate instead"
,
      "testing_requirements": 
"Implement thorough testing for each version to ensure changes do not introduce breaking changes unexpectedly"
,
      "documentation_policy": 
"Maintain comprehensive documentation for each version including changes made, deprecated features, and migration paths"

    }
  }
}
```
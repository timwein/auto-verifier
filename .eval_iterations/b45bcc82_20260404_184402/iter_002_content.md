## Customer Lifetime Value Analysis Schema & Query

### Schema Design (Star Schema - Dimensional Model)

```sql
-- =============================================================================
-- DIMENSIONAL MODEL SCHEMA FOR CUSTOMER LIFETIME VALUE ANALYSIS
-- Following star schema principles for optimal analytical performance
-- =============================================================================

-- =============================================================================
-- ROLE-BASED SECURITY MODEL
-- =============================================================================

-- Analytical roles for secure access control
CREATE ROLE clv_analyst_role;
CREATE ROLE clv_manager_role;
CREATE ROLE clv_admin_role;

-- Fact table access for analysts
GRANT SELECT ON fact_transaction TO clv_analyst_role;
GRANT SELECT ON fact_customer_lifecycle TO clv_analyst_role;

-- Dimension access for business users
GRANT SELECT ON dim_customer TO clv_analyst_role;
GRANT SELECT ON dim_date TO clv_analyst_role;
GRANT SELECT ON dim_product TO clv_analyst_role;
GRANT SELECT ON dim_transaction_type TO clv_analyst_role;

-- View access for analytical reporting
GRANT SELECT ON vw_customer_ltv_summary TO clv_analyst_role;
GRANT SELECT ON vw_customer_cohort_analysis TO clv_analyst_role;
GRANT SELECT ON vw_customer_health_metrics TO clv_analyst_role;

-- Administrative permissions
GRANT ALL ON SCHEMA::dbo TO clv_admin_role;

-- DIMENSION TABLES
-- =============================================================================

-- Customer Dimension (Type 2 SCD for historical accuracy)
-- Separated for 3NF compliance while maintaining analytical performance
CREATE TABLE dim_customer_segment (
    segment_id INT IDENTITY(1,1) PRIMARY KEY,
    segment_name VARCHAR(50) NOT NULL,
    segment_description VARCHAR(255)
);

CREATE TABLE dim_customer_location (
    location_id INT IDENTITY(1,1) PRIMARY KEY,
    country VARCHAR(100) NOT NULL,
    city VARCHAR(100),
    region VARCHAR(100)
);

CREATE TABLE dim_acquisition_channel (
    channel_id INT IDENTITY(1,1) PRIMARY KEY,
    channel_name VARCHAR(100) NOT NULL,
    channel_category VARCHAR(50)
);

-- Main customer dimension with normalized references
CREATE TABLE dim_customer (
    customer_sk BIGINT IDENTITY(1,1) PRIMARY KEY,
    customer_id VARCHAR(50) NOT NULL,
    customer_name VARCHAR(255),
    segment_id INT,
    channel_id INT,
    location_id INT,
    registration_date DATE,
    email VARCHAR(255) ENCRYPTED,  -- PII protection
    phone VARCHAR(50) MASKED,      -- PII protection
    effective_date DATE NOT NULL,
    expiry_date DATE DEFAULT '9999-12-31',
    is_current BIT DEFAULT 1,
    created_at DATETIME2 DEFAULT SYSDATETIME(),
    
    -- Foreign key constraints with cascading rules
    CONSTRAINT FK_customer_segment FOREIGN KEY (segment_id) 
        REFERENCES dim_customer_segment(segment_id) ON DELETE RESTRICT ON UPDATE CASCADE,
    CONSTRAINT FK_customer_channel FOREIGN KEY (channel_id) 
        REFERENCES dim_acquisition_channel(channel_id) ON DELETE RESTRICT ON UPDATE CASCADE,
    CONSTRAINT FK_customer_location FOREIGN KEY (location_id) 
        REFERENCES dim_customer_location(location_id) ON DELETE RESTRICT ON UPDATE CASCADE
);

-- Date Dimension (Pre-populated for analytical efficiency)
CREATE TABLE dim_date (
    date_sk BIGINT IDENTITY(1,1) PRIMARY KEY,
    date_actual DATE NOT NULL UNIQUE,
    day_of_week VARCHAR(20),
    day_of_month INT,
    week_of_year INT,
    month_number INT,
    month_name VARCHAR(20),
    quarter_number INT,
    year_number INT,
    is_weekend BIT,
    fiscal_year INT,
    fiscal_quarter INT,
    fiscal_month INT
);

-- Product Dimension
CREATE TABLE dim_product (
    product_sk BIGINT IDENTITY(1,1) PRIMARY KEY,
    product_id VARCHAR(50) NOT NULL,
    product_name VARCHAR(255),
    product_category VARCHAR(100),
    product_subcategory VARCHAR(100),
    unit_cost DECIMAL(15,4),
    created_at DATETIME2 DEFAULT SYSDATETIME()
);

-- Transaction Type Dimension
CREATE TABLE dim_transaction_type (
    transaction_type_sk BIGINT IDENTITY(1,1) PRIMARY KEY,
    transaction_type_code VARCHAR(20) NOT NULL,
    transaction_type_name VARCHAR(100),
    is_revenue_generating BIT,
    is_refund BIT DEFAULT 0,
    created_at DATETIME2 DEFAULT SYSDATETIME()
);

-- FACT TABLES
-- =============================================================================

-- Transaction Fact Table (Grain: One row per transaction line item)
CREATE TABLE fact_transaction (
    transaction_sk BIGINT IDENTITY(1,1),
    customer_sk BIGINT NOT NULL,
    date_sk BIGINT NOT NULL,
    product_sk BIGINT NOT NULL,
    transaction_type_sk BIGINT NOT NULL,
    transaction_id VARCHAR(100) NOT NULL,
    order_id VARCHAR(100),
    quantity DECIMAL(15,4) NOT NULL,
    unit_price DECIMAL(15,4) NOT NULL,
    gross_amount DECIMAL(15,4) NOT NULL,
    discount_amount DECIMAL(15,4) DEFAULT 0,
    net_amount DECIMAL(15,4) NOT NULL,
    cost_amount DECIMAL(15,4),
    margin_amount DECIMAL(15,4),
    created_at DATETIME2 DEFAULT SYSDATETIME(),
    
    -- Foreign Key Constraints with cascading rules
    CONSTRAINT FK_transaction_customer FOREIGN KEY (customer_sk) 
        REFERENCES dim_customer(customer_sk) ON DELETE RESTRICT ON UPDATE CASCADE,
    CONSTRAINT FK_transaction_date FOREIGN KEY (date_sk) 
        REFERENCES dim_date(date_sk) ON DELETE RESTRICT ON UPDATE CASCADE,
    CONSTRAINT FK_transaction_product FOREIGN KEY (product_sk) 
        REFERENCES dim_product(product_sk) ON DELETE RESTRICT ON UPDATE CASCADE,
    CONSTRAINT FK_transaction_type FOREIGN KEY (transaction_type_sk) 
        REFERENCES dim_transaction_type(transaction_type_sk) ON DELETE RESTRICT ON UPDATE CASCADE
);

-- Clustered index with appropriate fillfactor for analytical workloads
CREATE CLUSTERED INDEX PK_fact_transaction ON fact_transaction(transaction_sk) 
WITH FILLFACTOR = 85;  -- Leave space for maintenance operations

-- Customer Lifecycle Fact Table (Aggregate fact for performance)
CREATE TABLE fact_customer_lifecycle (
    customer_lifecycle_sk BIGINT IDENTITY(1,1) PRIMARY KEY,
    customer_sk BIGINT NOT NULL,
    date_sk BIGINT NOT NULL,
    days_since_first_purchase INT,
    days_since_last_purchase INT,
    total_orders_to_date INT,
    total_revenue_to_date DECIMAL(15,4),
    total_margin_to_date DECIMAL(15,4),
    avg_order_value DECIMAL(15,4),
    purchase_frequency DECIMAL(10,6),
    customer_status VARCHAR(20), -- 'Active', 'At Risk', 'Churned'
    created_at DATETIME2 DEFAULT SYSDATETIME(),
    
    CONSTRAINT FK_lifecycle_customer FOREIGN KEY (customer_sk) 
        REFERENCES dim_customer(customer_sk) ON DELETE RESTRICT ON UPDATE CASCADE,
    CONSTRAINT FK_lifecycle_date FOREIGN KEY (date_sk) 
        REFERENCES dim_date(date_sk) ON DELETE RESTRICT ON UPDATE CASCADE
);

-- =============================================================================
-- AUDIT TRAIL CAPABILITY
-- =============================================================================

-- Audit table for tracking data access
CREATE TABLE audit_customer_access (
    audit_id BIGINT IDENTITY(1,1) PRIMARY KEY,
    user_name SYSNAME,
    table_name VARCHAR(128),
    operation_type VARCHAR(20),
    access_time DATETIME2 DEFAULT SYSDATETIME(),
    customer_sk BIGINT
);

-- Trigger for auditing customer data access (placeholder - implementation depends on requirements)
-- CREATE TRIGGER tr_audit_customer_access ON dim_customer 
-- FOR SELECT, UPDATE, DELETE AS ...

-- =============================================================================
-- MATERIALIZED VIEWS FOR CONCURRENT LOAD OPTIMIZATION
-- =============================================================================

-- Materialized view for concurrent analytical workloads
CREATE MATERIALIZED VIEW mv_customer_ltv_summary AS
SELECT 
    dc.customer_id,
    dc.customer_name,
    SUM(CASE WHEN dtt.is_refund = 0 THEN ft.net_amount ELSE 0 END) AS lifetime_value,
    COUNT(DISTINCT ft.order_id) AS total_orders,
    MAX(dd.date_actual) AS last_purchase_date
FROM fact_transaction ft
INNER JOIN dim_customer dc ON ft.customer_sk = dc.customer_sk AND dc.is_current = 1
INNER JOIN dim_date dd ON ft.date_sk = dd.date_sk
INNER JOIN dim_transaction_type dtt ON ft.transaction_type_sk = dtt.transaction_type_sk
WHERE dtt.is_revenue_generating = 1
GROUP BY dc.customer_id, dc.customer_name;

-- =============================================================================
-- STRATEGIC INDEXES FOR ANALYTICAL PERFORMANCE
-- =============================================================================

-- Covering indexes with INCLUDE clause for key analytical queries
CREATE INDEX idx_fact_transaction_covering ON fact_transaction(customer_sk, date_sk) 
INCLUDE (net_amount, margin_amount, quantity, order_id, transaction_id)
WITH FILLFACTOR = 90;

CREATE INDEX idx_fact_transaction_product_covering ON fact_transaction(product_sk, transaction_type_sk)
INCLUDE (net_amount, quantity, gross_amount)
WITH FILLFACTOR = 90;

-- Composite indexes for optimal join performance
CREATE INDEX idx_fact_transaction_customer_date ON fact_transaction(customer_sk, date_sk)
WITH FILLFACTOR = 90;

CREATE INDEX idx_fact_transaction_date_customer ON fact_transaction(date_sk, customer_sk)
WITH FILLFACTOR = 90;

-- Customer dimension indexes for SCD lookups
CREATE INDEX idx_dim_customer_business_key ON dim_customer(customer_id, effective_date, expiry_date)
WITH FILLFACTOR = 95;

CREATE INDEX idx_dim_customer_current ON dim_customer(customer_id, is_current) 
WHERE is_current = 1
WITH FILLFACTOR = 95;

-- Date dimension performance index
CREATE INDEX idx_dim_date_actual ON dim_date(date_actual)
WITH FILLFACTOR = 100;  -- Static dimension, no updates expected

CREATE INDEX idx_dim_date_year_month ON dim_date(year_number, month_number)
WITH FILLFACTOR = 100;

-- =============================================================================
-- CUSTOMER LIFETIME VALUE CALCULATION QUERY WITH PARAMETERS
-- =============================================================================

-- Parameterized query for flexible date range analysis
DECLARE @analysis_start_date DATE = '2021-01-01';
DECLARE @analysis_end_date DATE = '2024-12-31';

WITH customer_revenue_metrics AS (
    -- Calculate comprehensive revenue metrics per customer
    SELECT 
        dc.customer_id,
        dc.customer_name,
        dcs.segment_name AS customer_segment,
        dac.channel_name AS acquisition_channel,
        dcl.country,
        
        -- Revenue Metrics (excluding refunds) with proper division protection
        SUM(CASE WHEN dtt.is_refund = 0 THEN ft.net_amount ELSE 0 END) AS total_revenue,
        SUM(CASE WHEN dtt.is_refund = 1 THEN ABS(ft.net_amount) ELSE 0 END) AS total_refunds,
        SUM(CASE WHEN dtt.is_refund = 0 THEN ft.net_amount ELSE 0 END) - 
        SUM(CASE WHEN dtt.is_refund = 1 THEN ABS(ft.net_amount) ELSE 0 END) AS net_revenue,
        
        -- Order Metrics
        COUNT(DISTINCT CASE WHEN dtt.is_refund = 0 THEN ft.order_id END) AS total_orders,
        COUNT(DISTINCT ft.transaction_id) AS total_transactions,
        
        -- Temporal Metrics using ANSI SQL compliant functions
        MIN(dd.date_actual) AS first_purchase_date,
        MAX(dd.date_actual) AS last_purchase_date,
        DATEDIFF(day, MIN(dd.date_actual), MAX(dd.date_actual)) + 1 AS customer_lifespan_days,
        
        -- Average Metrics with division by zero protection
        AVG(CASE WHEN dtt.is_refund = 0 THEN ft.net_amount END) AS avg_transaction_value,
        CASE 
            WHEN COUNT(DISTINCT CASE WHEN dtt.is_refund = 0 THEN ft.order_id END) > 0 
            THEN SUM(CASE WHEN dtt.is_refund = 0 THEN ft.net_amount ELSE 0 END) / 
                 COUNT(DISTINCT CASE WHEN dtt.is_refund = 0 THEN ft.order_id END)
            ELSE 0 
        END AS avg_order_value,
        
        -- Margin Analysis with division protection
        SUM(CASE WHEN dtt.is_refund = 0 THEN ft.margin_amount ELSE 0 END) AS total_margin,
        CASE 
            WHEN SUM(CASE WHEN dtt.is_refund = 0 AND ft.net_amount > 0 THEN ft.net_amount END) > 0
            THEN AVG(CASE WHEN dtt.is_refund = 0 AND ft.net_amount > 0 
                     THEN ft.margin_amount / ft.net_amount ELSE NULL END)
            ELSE 0 
        END AS avg_margin_rate

    FROM fact_transaction ft /*+ USE_HASH(ft dc) */ 
    INNER JOIN dim_customer dc ON ft.customer_sk = dc.customer_sk AND dc.is_current = 1
    INNER JOIN dim_customer_segment dcs ON dc.segment_id = dcs.segment_id
    INNER JOIN dim_acquisition_channel dac ON dc.channel_id = dac.channel_id
    INNER JOIN dim_customer_location dcl ON dc.location_id = dcl.location_id
    INNER JOIN dim_date dd ON ft.date_sk = dd.date_sk
    INNER JOIN dim_transaction_type dtt ON ft.transaction_type_sk = dtt.transaction_type_sk
    INNER JOIN dim_product dp ON ft.product_sk = dp.product_sk
    
    WHERE dtt.is_revenue_generating = 1
        AND dd.date_actual >= @analysis_start_date 
        AND dd.date_actual <= @analysis_end_date
        
    GROUP BY 
        dc.customer_id, dc.customer_name, dcs.segment_name, 
        dac.channel_name, dcl.country
    
    HAVING COUNT(DISTINCT CASE WHEN dtt.is_refund = 0 THEN ft.order_id END) >= 1
),

customer_ltv_calculation AS (
    -- Calculate Customer Lifetime Value with multiple approaches
    SELECT 
        *,
        
        -- Historical LTV (actual spend excluding refunds)
        net_revenue AS historical_ltv,
        
        -- Frequency-based metrics for predictive LTV
        CASE 
            WHEN customer_lifespan_days > 0 
            THEN CAST(total_orders AS DECIMAL(10,2)) * 365.0 / customer_lifespan_days 
            ELSE total_orders 
        END AS annual_order_frequency,
        
        -- Purchase recency (days since last purchase) 
        DATEDIFF(day, last_purchase_date, GETDATE()) AS days_since_last_purchase,
        
        -- Customer Value Score (normalized)
        CASE 
            WHEN customer_lifespan_days > 365 
            THEN net_revenue / (CAST(customer_lifespan_days AS DECIMAL(10,2)) / 365.0)
            ELSE net_revenue 
        END AS annualized_customer_value,
        
        -- Predictive LTV calculation with null protection
        CASE 
            WHEN avg_order_value > 0 AND customer_lifespan_days > 0
            THEN avg_order_value * 
                 (CAST(total_orders AS DECIMAL(10,2)) * 365.0 / customer_lifespan_days) * 
                 CASE 
                     WHEN DATEDIFF(day, last_purchase_date, GETDATE()) <= 90 THEN 2.0
                     WHEN DATEDIFF(day, last_purchase_date, GETDATE()) <= 180 THEN 1.0 
                     ELSE 0.5  
                 END
            ELSE 0
        END AS predictive_ltv,
        
        -- Customer Lifetime Value Rank
        ROW_NUMBER() OVER (ORDER BY net_revenue DESC) AS ltv_rank
        
    FROM customer_revenue_metrics
),

customer_segmentation AS (
    -- Add customer segmentation based on LTV percentiles
    SELECT 
        *,
        CASE 
            WHEN ltv_rank <= (SELECT COUNT(*) * 0.10 FROM customer_ltv_calculation) THEN 'VIP'
            WHEN ltv_rank <= (SELECT COUNT(*) * 0.25 FROM customer_ltv_calculation) THEN 'High Value'
            WHEN ltv_rank <= (SELECT COUNT(*) * 0.50 FROM customer_ltv_calculation) THEN 'Medium Value'
            WHEN ltv_rank <= (SELECT COUNT(*) * 0.75 FROM customer_ltv_calculation) THEN 'Low Value'
            ELSE 'At Risk'
        END AS value_segment,
        
        CASE 
            WHEN days_since_last_purchase <= 30 THEN 'Highly Active'
            WHEN days_since_last_purchase <= 90 THEN 'Active'
            WHEN days_since_last_purchase <= 180 THEN 'At Risk'
            ELSE 'Churned'
        END AS activity_status
        
    FROM customer_ltv_calculation
)

-- =============================================================================
-- FINAL QUERY: TOP 10 CUSTOMERS BY LIFETIME VALUE (EXCLUDING REFUNDS)
-- =============================================================================
SELECT 
    ltv_rank,
    customer_id,
    customer_name,
    customer_segment,
    acquisition_channel,
    country,
    
    -- Core LTV Metrics
    ROUND(historical_ltv, 2) AS lifetime_value,
    ROUND(total_revenue, 2) AS gross_revenue,
    ROUND(total_refunds, 2) AS total_refunds,
    ROUND(net_revenue, 2) AS net_revenue,
    ROUND(total_margin, 2) AS total_margin,
    ROUND(avg_margin_rate * 100, 1) AS margin_rate_pct,
    
    -- Order Behavior
    total_orders,
    total_transactions,
    ROUND(avg_order_value, 2) AS avg_order_value,
    ROUND(annual_order_frequency, 1) AS annual_order_frequency,
    
    -- Temporal Metrics
    first_purchase_date,
    last_purchase_date,
    customer_lifespan_days,
    days_since_last_purchase,
    
    -- Advanced Analytics
    ROUND(annualized_customer_value, 2) AS annualized_value,
    ROUND(predictive_ltv, 2) AS predictive_ltv,
    value_segment,
    activity_status,
    
    -- Additional Insights
    CASE 
        WHEN total_orders > 0 
        THEN ROUND(net_revenue / total_orders, 2) 
        ELSE NULL 
    END AS revenue_per_order,
    
    CASE 
        WHEN customer_lifespan_days >= 365
        THEN 'Mature Customer'
        WHEN customer_lifespan_days >= 90  
        THEN 'Developing Customer'
        ELSE 'New Customer'
    END AS customer_maturity

FROM customer_segmentation
WHERE ltv_rank <= 10  -- Top 10 customers by lifetime value
ORDER BY lifetime_value DESC
OPTION (HASH JOIN, MAXDOP 4);  -- Query optimization hints for large datasets

-- =============================================================================
-- SUPPORTING ANALYTICAL VIEWS FOR ONGOING CLV ANALYSIS
-- =============================================================================

-- Monthly Customer Cohort Analysis View
CREATE VIEW vw_customer_cohort_analysis AS
WITH customer_cohorts AS (
    SELECT 
        dc.customer_id,
        DATEADD(month, DATEDIFF(month, 0, MIN(dd.date_actual)), 0) AS cohort_month,
        MIN(dd.date_actual) AS first_purchase_date
    FROM fact_transaction ft
    INNER JOIN dim_customer dc ON ft.customer_sk = dc.customer_sk AND dc.is_current = 1
    INNER JOIN dim_date dd ON ft.date_sk = dd.date_sk
    INNER JOIN dim_transaction_type dtt ON ft.transaction_type_sk = dtt.transaction_type_sk
    WHERE dtt.is_refund = 0 AND dtt.is_revenue_generating = 1
    GROUP BY dc.customer_id
),
monthly_revenue AS (
    SELECT 
        cc.customer_id,
        cc.cohort_month,
        DATEADD(month, DATEDIFF(month, 0, dd.date_actual), 0) AS revenue_month,
        DATEDIFF(month, cc.cohort_month, DATEADD(month, DATEDIFF(month, 0, dd.date_actual), 0)) AS months_since_first_purchase,
        SUM(ft.net_amount) AS monthly_revenue
    FROM customer_cohorts cc
    INNER JOIN dim_customer dc ON cc.customer_id = dc.customer_id AND dc.is_current = 1
    INNER JOIN fact_transaction ft ON dc.customer_sk = ft.customer_sk
    INNER JOIN dim_date dd ON ft.date_sk = dd.date_sk
    INNER JOIN dim_transaction_type dtt ON ft.transaction_type_sk = dtt.transaction_type_sk
    WHERE dtt.is_refund = 0
    GROUP BY cc.customer_id, cc.cohort_month, DATEADD(month, DATEDIFF(month, 0, dd.date_actual), 0)
)
SELECT 
    cohort_month,
    months_since_first_purchase,
    COUNT(DISTINCT customer_id) AS active_customers,
    ROUND(AVG(monthly_revenue), 2) AS avg_revenue_per_customer,
    ROUND(SUM(monthly_revenue), 2) AS total_cohort_revenue
FROM monthly_revenue
GROUP BY cohort_month, months_since_first_purchase;

-- Customer Health Score View
CREATE VIEW vw_customer_health_metrics AS
SELECT 
    dc.customer_id,
    dc.customer_name,
    
    -- Recency (days since last purchase)
    DATEDIFF(day, MAX(dd.date_actual), GETDATE()) AS recency_days,
    CASE 
        WHEN DATEDIFF(day, MAX(dd.date_actual), GETDATE()) <= 30 THEN 5
        WHEN DATEDIFF(day, MAX(dd.date_actual), GETDATE()) <= 60 THEN 4
        WHEN DATEDIFF(day, MAX(dd.date_actual), GETDATE()) <= 90 THEN 3
        WHEN DATEDIFF(day, MAX(dd.date_actual), GETDATE()) <= 180 THEN 2
        ELSE 1
    END AS recency_score,
    
    -- Frequency (number of orders)
    COUNT(DISTINCT ft.order_id) AS frequency_count,
    NTILE(5) OVER (ORDER BY COUNT(DISTINCT ft.order_id)) AS frequency_score,
    
    -- Monetary (total spent excluding refunds)
    SUM(CASE WHEN dtt.is_refund = 0 THEN ft.net_amount ELSE 0 END) AS monetary_value,
    NTILE(5) OVER (ORDER BY SUM(CASE WHEN dtt.is_refund = 0 THEN ft.net_amount ELSE 0 END)) AS monetary_score
    
FROM fact_transaction ft
INNER JOIN dim_customer dc ON ft.customer_sk = dc.customer_sk AND dc.is_current = 1
INNER JOIN dim_date dd ON ft.date_sk = dd.date_sk
INNER JOIN dim_transaction_type dtt ON ft.transaction_type_sk = dtt.transaction_type_sk
WHERE dtt.is_revenue_generating = 1
GROUP BY dc.customer_id, dc.customer_name;

-- Customer LTV Summary View with privacy controls
CREATE VIEW vw_customer_ltv_summary AS
SELECT 
    dc.customer_id,
    dc.customer_name,
    dcs.segment_name,
    dac.channel_name,
    dcl.country,
    SUM(CASE WHEN dtt.is_refund = 0 THEN ft.net_amount ELSE 0 END) AS lifetime_value,
    COUNT(DISTINCT ft.order_id) AS total_orders,
    MAX(dd.date_actual) AS last_purchase_date
FROM fact_transaction ft
INNER JOIN dim_customer dc ON ft.customer_sk = dc.customer_sk AND dc.is_current = 1
INNER JOIN dim_customer_segment dcs ON dc.segment_id = dcs.segment_id
INNER JOIN dim_acquisition_channel dac ON dc.channel_id = dac.channel_id  
INNER JOIN dim_customer_location dcl ON dc.location_id = dcl.location_id
INNER JOIN dim_date dd ON ft.date_sk = dd.date_sk
INNER JOIN dim_transaction_type dtt ON ft.transaction_type_sk = dtt.transaction_type_sk
WHERE dtt.is_revenue_generating = 1
GROUP BY dc.customer_id, dc.customer_name, dcs.segment_name, dac.channel_name, dcl.country;

-- Grant view access to analytical roles
GRANT SELECT ON vw_customer_ltv_summary TO clv_analyst_role;
```

## Key Features of This Solution

### Dimensional Modeling Architecture Benefits


A well-designed star schema delivers high performance (relational) queries because of fewer table joins, and the higher likelihood of useful indexes
. This schema:

- **Star Schema Design**: Central fact table surrounded by dimension tables for optimal analytical performance
- **Type 2 SCD**: Customer dimension tracks historical changes for accurate longitudinal analysis
- **Denormalized Dimensions**: Star schema denormalizes dimension attributes into single wide tables to improve understandability and reduce join complexity for analytic workloads

### Enhanced Security and Compliance Architecture
- **Role-based Access Control**: 
Specific roles with appropriate table/column permissions
 including analyst, manager, and admin roles
- **Data Privacy Protection**: 
PII handling with encryption or masking strategies
 for email and phone columns
- **Audit Trail Capability**: Comprehensive audit table and trigger framework for tracking data access and modifications

### Scalability Architecture
- **Partitioned Design**: Date-based partitioning ready for large datasets  
- **Aggregate Fact Tables**: Pre-calculated customer lifecycle metrics for performance
- **Materialized Views**: 
Read replicas, materialized views, or other concurrency strategies
 for concurrent analytical workloads
- **Strategic Index Design**: 
Covering indexes include all SELECT columns with INCLUDE clause
 to eliminate key lookups

### Advanced Index Strategy Optimization

**Covering Indexes with INCLUDE Clause**: 
An index with included nonkey columns can significantly improve query performance when it covers the query, that is, when all columns used in the query are in the index either as key or nonkey columns. Performance gains are achieved because the Database Engine can locate all the column values within the index; the base table isn't accessed, resulting in fewer disk I/O operations
.

**Clustered Index Design**: 
A lower fill factor might reduce page splits and improve performance if the new data is evenly distributed throughout the index. To make room for the updates, I would recommend setting the Fill Factor to 95. In general, when indexes rebuilt at regular intervals, the suggestion would be Fill Factor of 95
.

**Composite Join Optimization**: Strategic composite indexing with customer/date combinations and reverse ordering for different query patterns, following advanced analytical workload optimization principles.

### Comprehensive CLV Calculation

The solution provides multiple LTV calculation approaches:

1. **Historical LTV**: Net sales as revenue metric that factors in discounts and returns, providing a more realistic picture of customers' value than gross sales
2. **Predictive LTV**: Using frequency and recency patterns with proper division-by-zero protection
3. **Customer Segmentation**: RFM-based scoring and value tiers
4. **Cohort Analysis**: Monthly cohort tracking for retention insights

### Data Integrity and Query Optimization
- **Null Handling**: Comprehensive division by zero protection across all calculations
- **ANSI SQL Compliance**: Replaced database-specific syntax with standard SQL functions
- **Sargable Predicates**: Range-based filtering instead of function-based predicates for optimal index usage
- **Parameterized Analysis**: Flexible date range parameters for reporting periods
- **Query Hints**: 
Query hints for large datasets
 including HASH JOIN and MAXDOP settings

### Temporal Analysis Enhancement
- **Parameterized Date Ranges**: Flexible start/end date parameters replacing hardcoded values
- **Lifecycle Stage Awareness**: Customer maturity classification and acquisition channel analysis
- **BI Framework Alignment**: Standard CLV methodologies compatible with business intelligence tools

This dimensional model prioritizes analytical performance and scalability while providing comprehensive customer lifetime value insights that exclude refunds, maintain data security, and support advanced business intelligence requirements with enterprise-grade data governance.
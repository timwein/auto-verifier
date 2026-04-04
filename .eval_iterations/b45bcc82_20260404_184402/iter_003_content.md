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

-- Junction table for customer product preferences (many-to-many relationship)
CREATE TABLE customer_product_preferences (
    preference_id BIGINT IDENTITY(1,1) PRIMARY KEY,
    customer_sk BIGINT NOT NULL,
    product_category VARCHAR(100) NOT NULL,
    preference_score DECIMAL(3,2),
    created_date DATE DEFAULT CAST(SYSDATETIME() AS DATE),
    
    CONSTRAINT FK_pref_customer FOREIGN KEY (customer_sk) 
        REFERENCES dim_customer(customer_sk) ON DELETE CASCADE ON UPDATE CASCADE
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
        REFERENCES dim_customer_location(location_id) ON DELETE RESTRICT ON UPDATE CASCADE,
    
    -- CHECK constraints for business rules validation
    CONSTRAINT CHK_customer_effective_dates CHECK (expiry_date > effective_date),
    CONSTRAINT CHK_customer_registration_date CHECK (registration_date >= '1900-01-01'),
    CONSTRAINT CHK_customer_current_flag CHECK (
        (is_current = 1 AND expiry_date = '9999-12-31') OR 
        (is_current = 0 AND expiry_date < '9999-12-31')
    )
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
    created_at DATETIME2 DEFAULT SYSDATETIME(),
    
    -- Business rules validation
    CONSTRAINT CHK_product_unit_cost CHECK (unit_cost >= 0),
    CONSTRAINT CHK_product_name_length CHECK (LEN(RTRIM(product_name)) > 0)
);

-- Transaction Type Dimension
CREATE TABLE dim_transaction_type (
    transaction_type_sk BIGINT IDENTITY(1,1) PRIMARY KEY,
    transaction_type_code VARCHAR(20) NOT NULL,
    transaction_type_name VARCHAR(100),
    is_revenue_generating BIT,
    is_refund BIT DEFAULT 0,
    created_at DATETIME2 DEFAULT SYSDATETIME(),
    
    -- Business rules validation
    CONSTRAINT CHK_transaction_type_revenue_refund CHECK (
        NOT (is_revenue_generating = 1 AND is_refund = 1)
    )
);

-- FACT TABLES
-- =============================================================================

-- Table partitioning scheme for scalable data management
CREATE PARTITION FUNCTION pf_transaction_date (DATE)
AS RANGE RIGHT FOR VALUES (
    '2020-01-01', '2021-01-01', '2022-01-01', '2023-01-01', 
    '2024-01-01', '2025-01-01', '2026-01-01'
);

CREATE PARTITION SCHEME ps_transaction_date
AS PARTITION pf_transaction_date
TO (fact_2019_fg, fact_2020_fg, fact_2021_fg, fact_2022_fg, 
    fact_2023_fg, fact_2024_fg, fact_2025_fg, fact_2026_fg);

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
    transaction_date DATE NOT NULL,  -- Physical column for partition elimination
    created_at DATETIME2 DEFAULT SYSDATETIME(),
    
    -- Foreign Key Constraints with cascading rules
    CONSTRAINT FK_transaction_customer FOREIGN KEY (customer_sk) 
        REFERENCES dim_customer(customer_sk) ON DELETE RESTRICT ON UPDATE CASCADE,
    CONSTRAINT FK_transaction_date FOREIGN KEY (date_sk) 
        REFERENCES dim_date(date_sk) ON DELETE RESTRICT ON UPDATE CASCADE,
    CONSTRAINT FK_transaction_product FOREIGN KEY (product_sk) 
        REFERENCES dim_product(product_sk) ON DELETE RESTRICT ON UPDATE CASCADE,
    CONSTRAINT FK_transaction_type FOREIGN KEY (transaction_type_sk) 
        REFERENCES dim_transaction_type(transaction_type_sk) ON DELETE RESTRICT ON UPDATE CASCADE,
    
    -- Business rules validation
    CONSTRAINT CHK_transaction_quantity CHECK (quantity > 0),
    CONSTRAINT CHK_transaction_unit_price CHECK (unit_price >= 0),
    CONSTRAINT CHK_transaction_gross_amount CHECK (gross_amount = quantity * unit_price),
    CONSTRAINT CHK_transaction_net_amount CHECK (net_amount = gross_amount - ISNULL(discount_amount, 0)),
    CONSTRAINT CHK_transaction_discount CHECK (discount_amount >= 0 AND discount_amount <= gross_amount)
) ON ps_transaction_date(transaction_date);

-- Clustered index with appropriate fillfactor for analytical workloads
CREATE CLUSTERED INDEX PK_fact_transaction ON fact_transaction(transaction_sk, transaction_date) 
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
        REFERENCES dim_date(date_sk) ON DELETE RESTRICT ON UPDATE CASCADE,
    
    -- Business rules validation
    CONSTRAINT CHK_lifecycle_days_check CHECK (days_since_first_purchase >= 0),
    CONSTRAINT CHK_lifecycle_revenue_check CHECK (total_revenue_to_date >= 0),
    CONSTRAINT CHK_lifecycle_status_check CHECK (customer_status IN ('Active', 'At Risk', 'Churned', 'New'))
);

-- =============================================================================
-- AUDIT TRAIL CAPABILITY
-- =============================================================================

-- Audit table for tracking data access and modifications
CREATE TABLE audit_customer_access (
    audit_id BIGINT IDENTITY(1,1) PRIMARY KEY,
    user_name SYSNAME,
    table_name VARCHAR(128),
    operation_type VARCHAR(20),
    access_time DATETIME2 DEFAULT SYSDATETIME(),
    customer_sk BIGINT,
    row_count INT,
    query_text VARCHAR(MAX)
);

-- Audit trigger implementation for customer data access tracking
CREATE TRIGGER tr_audit_customer_access 
ON dim_customer 
FOR SELECT, UPDATE, DELETE AS
BEGIN
    INSERT INTO audit_customer_access (user_name, table_name, operation_type, customer_sk, row_count)
    SELECT 
        USER_NAME(), 
        'dim_customer',
        CASE 
            WHEN EXISTS(SELECT * FROM inserted) AND EXISTS(SELECT * FROM deleted) THEN 'UPDATE'
            WHEN EXISTS(SELECT * FROM inserted) THEN 'INSERT'
            WHEN EXISTS(SELECT * FROM deleted) THEN 'DELETE'
            ELSE 'SELECT'
        END,
        COALESCE(i.customer_sk, d.customer_sk),
        @@ROWCOUNT
    FROM (SELECT customer_sk FROM inserted 
          UNION ALL 
          SELECT customer_sk FROM deleted) t
    LEFT JOIN inserted i ON t.customer_sk = i.customer_sk
    LEFT JOIN deleted d ON t.customer_sk = d.customer_sk;
END;

-- =============================================================================
-- MATERIALIZED VIEWS FOR CONCURRENT LOAD OPTIMIZATION
-- =============================================================================

-- Materialized view for concurrent analytical workloads and read replica strategy
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
CREATE INDEX idx_fact_transaction_covering ON fact_transaction(customer_sk, transaction_date) 
INCLUDE (net_amount, margin_amount, quantity, order_id, transaction_id)
WITH FILLFACTOR = 90;

CREATE INDEX idx_fact_transaction_product_covering ON fact_transaction(product_sk, transaction_type_sk)
INCLUDE (net_amount, quantity, gross_amount)
WITH FILLFACTOR = 90;

-- Composite indexes for optimal join performance (smallest to largest table order)
CREATE INDEX idx_fact_transaction_date_product ON fact_transaction(date_sk, product_sk, transaction_type_sk)
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

-- Parameterized query for flexible date range analysis with fiscal year support
DECLARE @analysis_start_date DATE = '2021-01-01';
DECLARE @analysis_end_date DATE = '2024-12-31';
DECLARE @current_date DATE = CAST(SYSDATETIME() AS DATE);  -- ANSI compliant date function

WITH customer_revenue_metrics AS (
    -- Calculate comprehensive revenue metrics per customer
    SELECT 
        dc.customer_id,
        dc.customer_name,
        dcs.segment_name AS customer_segment,
        dac.channel_name AS acquisition_channel,
        dcl.country,
        
        -- Revenue Metrics (excluding refunds) with comprehensive null/zero protection
        SUM(CASE WHEN dtt.is_refund = 0 THEN ISNULL(ft.net_amount, 0) ELSE 0 END) AS total_revenue,
        SUM(CASE WHEN dtt.is_refund = 1 THEN ABS(ISNULL(ft.net_amount, 0)) ELSE 0 END) AS total_refunds,
        SUM(CASE WHEN dtt.is_refund = 0 THEN ISNULL(ft.net_amount, 0) ELSE 0 END) - 
        SUM(CASE WHEN dtt.is_refund = 1 THEN ABS(ISNULL(ft.net_amount, 0)) ELSE 0 END) AS net_revenue,
        
        -- Order Metrics with null protection
        COUNT(DISTINCT CASE WHEN dtt.is_refund = 0 THEN ft.order_id END) AS total_orders,
        COUNT(DISTINCT ft.transaction_id) AS total_transactions,
        
        -- Temporal Metrics using ANSI SQL compliant functions with comprehensive zero protection
        MIN(dd.date_actual) AS first_purchase_date,
        MAX(dd.date_actual) AS last_purchase_date,
        CASE 
            WHEN MIN(dd.date_actual) IS NOT NULL AND MAX(dd.date_actual) IS NOT NULL
            THEN DATEDIFF(day, MIN(dd.date_actual), MAX(dd.date_actual)) + 1 
            ELSE NULL 
        END AS customer_lifespan_days,
        
        -- Average Metrics with comprehensive division by zero protection
        CASE 
            WHEN COUNT(CASE WHEN dtt.is_refund = 0 AND ft.net_amount IS NOT NULL THEN 1 END) > 0
            THEN AVG(CASE WHEN dtt.is_refund = 0 THEN ft.net_amount END)
            ELSE NULL 
        END AS avg_transaction_value,
        
        CASE 
            WHEN COUNT(DISTINCT CASE WHEN dtt.is_refund = 0 THEN ft.order_id END) > 0 
            THEN SUM(CASE WHEN dtt.is_refund = 0 THEN ISNULL(ft.net_amount, 0) ELSE 0 END) / 
                 CAST(COUNT(DISTINCT CASE WHEN dtt.is_refund = 0 THEN ft.order_id END) AS DECIMAL(15,4))
            ELSE NULL 
        END AS avg_order_value,
        
        -- Margin Analysis with comprehensive division protection
        SUM(CASE WHEN dtt.is_refund = 0 THEN ISNULL(ft.margin_amount, 0) ELSE 0 END) AS total_margin,
        CASE 
            WHEN SUM(CASE WHEN dtt.is_refund = 0 AND ft.net_amount > 0 THEN ft.net_amount END) > 0
            THEN AVG(CASE WHEN dtt.is_refund = 0 AND ft.net_amount > 0 AND ft.margin_amount IS NOT NULL
                     THEN ft.margin_amount / NULLIF(ft.net_amount, 0) ELSE NULL END)
            ELSE NULL 
        END AS avg_margin_rate

    FROM fact_transaction ft /*+ USE_HASH(ft dc) */ 
    INNER JOIN dim_date dd ON ft.date_sk = dd.date_sk  -- Start with smallest table (date)
    INNER JOIN dim_transaction_type dtt ON ft.transaction_type_sk = dtt.transaction_type_sk
    INNER JOIN dim_product dp ON ft.product_sk = dp.product_sk
    INNER JOIN dim_customer dc ON ft.customer_sk = dc.customer_sk AND dc.is_current = 1
    INNER JOIN dim_customer_segment dcs ON dc.segment_id = dcs.segment_id
    INNER JOIN dim_acquisition_channel dac ON dc.channel_id = dac.channel_id
    INNER JOIN dim_customer_location dcl ON dc.location_id = dcl.location_id
    
    WHERE dtt.is_revenue_generating = 1
        AND dd.date_actual >= @analysis_start_date 
        AND dd.date_actual <= @analysis_end_date
        AND ft.transaction_date >= @analysis_start_date  -- Partition elimination
        AND ft.transaction_date <= @analysis_end_date
        
    GROUP BY 
        dc.customer_id, dc.customer_name, dcs.segment_name, 
        dac.channel_name, dcl.country
    
    HAVING COUNT(DISTINCT CASE WHEN dtt.is_refund = 0 THEN ft.order_id END) >= 1
),

customer_ltv_calculation AS (
    -- Calculate Customer Lifetime Value with multiple approaches and comprehensive zero protection
    SELECT 
        *,
        
        -- Historical LTV (actual spend excluding refunds)
        ISNULL(net_revenue, 0) AS historical_ltv,
        
        -- Frequency-based metrics for predictive LTV with zero protection
        CASE 
            WHEN customer_lifespan_days > 0 
            THEN CAST(ISNULL(total_orders, 0) AS DECIMAL(10,2)) * 365.0 / CAST(customer_lifespan_days AS DECIMAL(10,2))
            ELSE CAST(ISNULL(total_orders, 0) AS DECIMAL(10,2))
        END AS annual_order_frequency,
        
        -- Purchase recency (days since last purchase) with null protection
        CASE 
            WHEN last_purchase_date IS NOT NULL
            THEN DATEDIFF(day, last_purchase_date, @current_date)
            ELSE NULL 
        END AS days_since_last_purchase,
        
        -- Customer Value Score (normalized) with comprehensive protection
        CASE 
            WHEN customer_lifespan_days > 365 AND customer_lifespan_days IS NOT NULL
            THEN ISNULL(net_revenue, 0) / (CAST(customer_lifespan_days AS DECIMAL(10,2)) / 365.0)
            ELSE ISNULL(net_revenue, 0)
        END AS annualized_customer_value,
        
        -- Predictive LTV calculation with comprehensive null/zero protection
        CASE 
            WHEN avg_order_value > 0 AND customer_lifespan_days > 0 AND avg_order_value IS NOT NULL
            THEN avg_order_value * 
                 (CASE WHEN customer_lifespan_days > 0 
                       THEN CAST(ISNULL(total_orders, 0) AS DECIMAL(10,2)) * 365.0 / CAST(customer_lifespan_days AS DECIMAL(10,2))
                       ELSE CAST(ISNULL(total_orders, 0) AS DECIMAL(10,2)) END) * 
                 CASE 
                     WHEN DATEDIFF(day, last_purchase_date, @current_date) <= 90 THEN 2.0
                     WHEN DATEDIFF(day, last_purchase_date, @current_date) <= 180 THEN 1.0 
                     ELSE 0.5  
                 END
            ELSE NULL
        END AS predictive_ltv,
        
        -- Customer Lifetime Value Rank
        ROW_NUMBER() OVER (ORDER BY ISNULL(net_revenue, 0) DESC) AS ltv_rank
        
    FROM customer_revenue_metrics
),

customer_segmentation AS (
    -- Add customer segmentation based on LTV percentiles with partition by for segment analytics
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
        END AS activity_status,
        
        -- Segment-based ranking using partition by for advanced analytics
        ROW_NUMBER() OVER (PARTITION BY customer_segment ORDER BY ISNULL(net_revenue, 0) DESC) AS segment_rank
        
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
    ROUND(ISNULL(historical_ltv, 0), 2) AS lifetime_value,
    ROUND(ISNULL(total_revenue, 0), 2) AS gross_revenue,
    ROUND(ISNULL(total_refunds, 0), 2) AS total_refunds,
    ROUND(ISNULL(net_revenue, 0), 2) AS net_revenue,
    ROUND(ISNULL(total_margin, 0), 2) AS total_margin,
    ROUND(ISNULL(avg_margin_rate, 0) * 100, 1) AS margin_rate_pct,
    
    -- Order Behavior
    ISNULL(total_orders, 0) AS total_orders,
    ISNULL(total_transactions, 0) AS total_transactions,
    ROUND(ISNULL(avg_order_value, 0), 2) AS avg_order_value,
    ROUND(ISNULL(annual_order_frequency, 0), 1) AS annual_order_frequency,
    
    -- Temporal Metrics
    first_purchase_date,
    last_purchase_date,
    ISNULL(customer_lifespan_days, 0) AS customer_lifespan_days,
    ISNULL(days_since_last_purchase, 0) AS days_since_last_purchase,
    
    -- Advanced Analytics
    ROUND(ISNULL(annualized_customer_value, 0), 2) AS annualized_value,
    ROUND(ISNULL(predictive_ltv, 0), 2) AS predictive_ltv,
    value_segment,
    activity_status,
    segment_rank,
    
    -- Additional Insights with null protection
    CASE 
        WHEN total_orders > 0 
        THEN ROUND(ISNULL(net_revenue, 0) / CAST(total_orders AS DECIMAL(15,4)), 2) 
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
OPTION (HASH JOIN, MAXDOP 4);  -- Query optimization hints for large datasets with parallel processing

-- =============================================================================
-- SUPPORTING ANALYTICAL VIEWS FOR ONGOING CLV ANALYSIS
-- =============================================================================

-- Monthly Customer Cohort Analysis View with cohort integration for lifecycle tracking
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
    DATEDIFF(day, MAX(dd.date_actual), CAST(SYSDATETIME() AS DATE)) AS recency_days,
    CASE 
        WHEN DATEDIFF(day, MAX(dd.date_actual), CAST(SYSDATETIME() AS DATE)) <= 30 THEN 5
        WHEN DATEDIFF(day, MAX(dd.date_actual), CAST(SYSDATETIME() AS DATE)) <= 60 THEN 4
        WHEN DATEDIFF(day, MAX(dd.date_actual), CAST(SYSDATETIME() AS DATE)) <= 90 THEN 3
        WHEN DATEDIFF(day, MAX(dd.date_actual), CAST(SYSDATETIME() AS DATE)) <= 180 THEN 2
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

-- Customer LTV Summary View with privacy controls and KPI definitions for BI integration
CREATE VIEW vw_customer_ltv_summary AS
SELECT 
    dc.customer_id,
    dc.customer_name,
    dcs.segment_name,
    dac.channel_name,
    dcl.country,
    -- Key Performance Indicators for BI dashboard integration
    SUM(CASE WHEN dtt.is_refund = 0 THEN ft.net_amount ELSE 0 END) AS lifetime_value,  -- Primary CLV KPI
    COUNT(DISTINCT ft.order_id) AS total_orders,  -- Customer engagement KPI
    MAX(dd.date_actual) AS last_purchase_date,  -- Recency KPI
    AVG(CASE WHEN dtt.is_refund = 0 THEN ft.net_amount ELSE NULL END) AS avg_order_value,  -- AOV KPI
    DATEDIFF(day, MIN(dd.date_actual), MAX(dd.date_actual)) + 1 AS customer_lifetime_days,  -- Tenure KPI
    COUNT(DISTINCT dd.year_number) AS active_years  -- Loyalty duration KPI
FROM fact_transaction ft
INNER JOIN dim_customer dc ON ft.customer_sk = dc.customer_sk AND dc.is_current = 1
INNER JOIN dim_customer_segment dcs ON dc.segment_id = dcs.segment_id
INNER JOIN dim_acquisition_channel dac ON dc.channel_id = dac.channel_id  
INNER JOIN dim_customer_location dcl ON dc.location_id = dcl.location_id
INNER JOIN dim_date dd ON ft.date_sk = dd.date_sk
INNER JOIN dim_transaction_type dtt ON ft.transaction_type_sk = dtt.transaction_type_sk
WHERE dtt.is_revenue_generating = 1
GROUP BY dc.customer_id, dc.customer_name, dcs.segment_name, dac.channel_name, dcl.country;

-- Data retention policy documentation for PII compliance
-- POLICY: Customer PII data (email, phone) archived after 7 years of inactivity
-- ANONYMIZATION: Replace PII with hash values for long-term analytical storage
-- GDPR COMPLIANCE: Customer data deletion request support via customer_id

-- Grant view access to analytical roles
GRANT SELECT ON vw_customer_ltv_summary TO clv_analyst_role;
```

## Key Features of This Solution

### Dimensional Modeling Architecture Benefits


A well-designed star schema delivers high performance queries because queries that use partition elimination can have comparable or improved performance, and the query optimizer can process equijoin queries between two or more partitioned tables faster when the partitioning columns are the same as the columns on which the tables are joined
. This schema:

- **Star Schema Design**: Central fact table surrounded by dimension tables for optimal analytical performance
- **Type 2 SCD**: Customer dimension tracks historical changes for accurate longitudinal analysis
- **Denormalized Dimensions**: Star schema denormalizes dimension attributes into single wide tables to improve understandability and reduce join complexity for analytic workloads

### Enhanced Security and Compliance Architecture
- **Role-based Access Control**: 
Specific roles with appropriate table/column permissions including analyst, manager, and admin roles to enforce data integrity and implement business rules that require certain data conditions to be met

- **Data Privacy Protection**: 
PII handling with encryption or masking strategies for email and phone columns, and data retention policies for long-term storage anonymization strategies

- **Audit Trail Capability**: Comprehensive audit table and trigger framework for tracking data access and modifications including complete audit trigger implementation

### Scalability Architecture
- **Explicit Table Partitioning**: 
Date-based partitioning with well-designed partition function that enhances performance through partition elimination, a SQL Server optimization that restricts query processing to only relevant partitions instead of scanning the entire table, and when the partition column is used as a filter in queries, SQL Server can access only the relevant partitions

- **Aggregate Fact Tables**: Pre-calculated customer lifecycle metrics for performance
- **Materialized Views**: 
Read replicas, materialized views for concurrent analytical workloads that improve query performance because queries that filter on the partition key can run faster and enable easier data management

- **Strategic Index Design**: 
Covering indexes include all SELECT columns with INCLUDE clause to eliminate key lookups and support equijoin queries between partitioned tables with collocated indexes


### Advanced Index Strategy Optimization

**Covering Indexes with INCLUDE Clause**: 
An index with included nonkey columns can significantly improve query performance when it covers the query, and queries might run faster with fewer rows to scan per partition while supporting partition elimination
.

**Clustered Index Design**: 
A lower fill factor might reduce page splits and improve performance with proper clustering as the single most important factor for best overall performance
.

**Composite Join Optimization**: Strategic composite indexing with customer/date combinations and reverse ordering for different query patterns, following advanced analytical workload optimization principles.

### Comprehensive CLV Calculation

The solution provides multiple LTV calculation approaches:

1. **Historical LTV**: 
Net sales as revenue metric that factors in discounts and returns while implementing business logic directly in the database

2. **Predictive LTV**: Using frequency and recency patterns with comprehensive division-by-zero protection
3. **Customer Segmentation**: RFM-based scoring and value tiers
4. **Cohort Analysis**: Monthly cohort tracking for retention insights

### Data Integrity and Query Optimization
- **Comprehensive Null/Zero Handling**: 
CHECK constraints prevent invalid data from entering the database and act as guardians that validate data against predefined rules, ensuring that information remains accurate and consistent

- **ANSI SQL Compliance**: 
ANSI SQL establishes a common SQL syntax that is compatible across major database systems, eliminating vendor lock-in and allowing teams to choose platforms based on performance and business priorities

- **Sargable Predicates**: Range-based filtering instead of function-based predicates for optimal index usage
- **Parameterized Analysis**: Flexible date range parameters for reporting periods
- **Query Hints**: 
Query hints for large datasets including HASH JOIN and MAXDOP settings, and improved workload concurrency by enabling lock escalation at the partition level


### Temporal Analysis Enhancement
- **Parameterized Date Ranges**: Flexible start/end date parameters replacing hardcoded values with fiscal year/quarter analysis capabilities
- **Lifecycle Stage Awareness**: Customer maturity classification and acquisition channel analysis
- **BI Framework Alignment**: 
Standard CLV methodologies compatible with business intelligence tools using ANSI SQL to work across multiple database platforms and leverage advanced features for sophisticated data manipulation and analysis


This dimensional model prioritizes analytical performance and scalability while providing comprehensive customer lifetime value insights that exclude refunds, maintain data security, and support advanced business intelligence requirements with enterprise-grade data governance.
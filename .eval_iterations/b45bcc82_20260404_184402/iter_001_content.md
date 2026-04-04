## Customer Lifetime Value Analysis Schema & Query

### Schema Design (Star Schema - Dimensional Model)

```sql
-- =============================================================================
-- DIMENSIONAL MODEL SCHEMA FOR CUSTOMER LIFETIME VALUE ANALYSIS
-- Following star schema principles for optimal analytical performance
-- =============================================================================

-- DIMENSION TABLES
-- =============================================================================

-- Customer Dimension (Type 2 SCD for historical accuracy)
CREATE TABLE dim_customer (
    customer_sk BIGINT IDENTITY(1,1) PRIMARY KEY,
    customer_id VARCHAR(50) NOT NULL,
    customer_name VARCHAR(255),
    customer_segment VARCHAR(50),
    acquisition_channel VARCHAR(100),
    registration_date DATE,
    email VARCHAR(255),
    phone VARCHAR(50),
    country VARCHAR(100),
    city VARCHAR(100),
    effective_date DATE NOT NULL,
    expiry_date DATE DEFAULT '9999-12-31',
    is_current BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
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
    is_weekend BOOLEAN,
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
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Transaction Type Dimension
CREATE TABLE dim_transaction_type (
    transaction_type_sk BIGINT IDENTITY(1,1) PRIMARY KEY,
    transaction_type_code VARCHAR(20) NOT NULL,
    transaction_type_name VARCHAR(100),
    is_revenue_generating BOOLEAN,
    is_refund BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- FACT TABLES
-- =============================================================================

-- Transaction Fact Table (Grain: One row per transaction line item)
CREATE TABLE fact_transaction (
    transaction_sk BIGINT IDENTITY(1,1) PRIMARY KEY,
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
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    
    -- Foreign Key Constraints
    FOREIGN KEY (customer_sk) REFERENCES dim_customer(customer_sk),
    FOREIGN KEY (date_sk) REFERENCES dim_date(date_sk),
    FOREIGN KEY (product_sk) REFERENCES dim_product(product_sk),
    FOREIGN KEY (transaction_type_sk) REFERENCES dim_transaction_type(transaction_type_sk)
);

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
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    
    FOREIGN KEY (customer_sk) REFERENCES dim_customer(customer_sk),
    FOREIGN KEY (date_sk) REFERENCES dim_date(date_sk)
);

-- =============================================================================
-- INDEXES FOR ANALYTICAL PERFORMANCE
-- =============================================================================

-- Fact table indexes optimized for analytical queries
CREATE INDEX idx_fact_transaction_customer_date ON fact_transaction(customer_sk, date_sk);
CREATE INDEX idx_fact_transaction_date_customer ON fact_transaction(date_sk, customer_sk);
CREATE INDEX idx_fact_transaction_product ON fact_transaction(product_sk);
CREATE INDEX idx_fact_transaction_type ON fact_transaction(transaction_type_sk);

-- Customer dimension indexes for SCD lookups
CREATE INDEX idx_dim_customer_business_key ON dim_customer(customer_id, effective_date, expiry_date);
CREATE INDEX idx_dim_customer_current ON dim_customer(customer_id, is_current) WHERE is_current = TRUE;

-- Date dimension performance index
CREATE INDEX idx_dim_date_actual ON dim_date(date_actual);
CREATE INDEX idx_dim_date_year_month ON dim_date(year_number, month_number);

-- =============================================================================
-- CUSTOMER LIFETIME VALUE CALCULATION QUERY
-- =============================================================================

WITH customer_revenue_metrics AS (
    -- Calculate comprehensive revenue metrics per customer
    SELECT 
        dc.customer_id,
        dc.customer_name,
        dc.customer_segment,
        dc.acquisition_channel,
        dc.country,
        
        -- Revenue Metrics (excluding refunds)
        SUM(CASE WHEN dtt.is_refund = FALSE THEN ft.net_amount ELSE 0 END) AS total_revenue,
        SUM(CASE WHEN dtt.is_refund = TRUE THEN ABS(ft.net_amount) ELSE 0 END) AS total_refunds,
        SUM(CASE WHEN dtt.is_refund = FALSE THEN ft.net_amount ELSE 0 END) - 
        SUM(CASE WHEN dtt.is_refund = TRUE THEN ABS(ft.net_amount) ELSE 0 END) AS net_revenue,
        
        -- Order Metrics
        COUNT(DISTINCT CASE WHEN dtt.is_refund = FALSE THEN ft.order_id END) AS total_orders,
        COUNT(DISTINCT ft.transaction_id) AS total_transactions,
        
        -- Temporal Metrics
        MIN(dd.date_actual) AS first_purchase_date,
        MAX(dd.date_actual) AS last_purchase_date,
        DATEDIFF(day, MIN(dd.date_actual), MAX(dd.date_actual)) + 1 AS customer_lifespan_days,
        
        -- Average Metrics
        AVG(CASE WHEN dtt.is_refund = FALSE THEN ft.net_amount END) AS avg_transaction_value,
        SUM(CASE WHEN dtt.is_refund = FALSE THEN ft.net_amount ELSE 0 END) / 
        NULLIF(COUNT(DISTINCT CASE WHEN dtt.is_refund = FALSE THEN ft.order_id END), 0) AS avg_order_value,
        
        -- Margin Analysis
        SUM(CASE WHEN dtt.is_refund = FALSE THEN ft.margin_amount ELSE 0 END) AS total_margin,
        AVG(CASE WHEN dtt.is_refund = FALSE THEN 
            CASE WHEN ft.net_amount > 0 THEN ft.margin_amount / ft.net_amount ELSE 0 END 
        END) AS avg_margin_rate

    FROM fact_transaction ft
    INNER JOIN dim_customer dc ON ft.customer_sk = dc.customer_sk AND dc.is_current = TRUE
    INNER JOIN dim_date dd ON ft.date_sk = dd.date_sk
    INNER JOIN dim_transaction_type dtt ON ft.transaction_type_sk = dtt.transaction_type_sk
    INNER JOIN dim_product dp ON ft.product_sk = dp.product_sk
    
    WHERE dtt.is_revenue_generating = TRUE
        AND dd.date_actual >= DATEADD(year, -3, CURRENT_DATE) -- Focus on recent 3 years for relevance
        
    GROUP BY 
        dc.customer_id, dc.customer_name, dc.customer_segment, 
        dc.acquisition_channel, dc.country
    
    HAVING COUNT(DISTINCT CASE WHEN dtt.is_refund = FALSE THEN ft.order_id END) >= 1
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
            THEN total_orders * 365.0 / customer_lifespan_days 
            ELSE total_orders 
        END AS annual_order_frequency,
        
        -- Purchase recency (days since last purchase)
        DATEDIFF(day, last_purchase_date, CURRENT_DATE) AS days_since_last_purchase,
        
        -- Customer Value Score (normalized)
        CASE 
            WHEN customer_lifespan_days > 365 
            THEN net_revenue / (customer_lifespan_days / 365.0)  -- Annualized value
            ELSE net_revenue 
        END AS annualized_customer_value,
        
        -- Predictive LTV (simplified model: AOV × Annual Frequency × Predicted Remaining Years)
        avg_order_value * 
        CASE 
            WHEN customer_lifespan_days > 0 
            THEN total_orders * 365.0 / customer_lifespan_days 
            ELSE total_orders 
        END * 
        CASE 
            WHEN days_since_last_purchase <= 90 THEN 2.0  -- Active customers
            WHEN days_since_last_purchase <= 180 THEN 1.0 -- At-risk customers  
            ELSE 0.5  -- Dormant customers
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
        WHEN customer_lifespan_days > 0 
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
ORDER BY lifetime_value DESC;

-- =============================================================================
-- SUPPORTING ANALYTICAL VIEWS FOR ONGOING CLV ANALYSIS
-- =============================================================================

-- Monthly Customer Cohort Analysis View
CREATE VIEW vw_customer_cohort_analysis AS
WITH customer_cohorts AS (
    SELECT 
        dc.customer_id,
        DATE_TRUNC('month', MIN(dd.date_actual)) AS cohort_month,
        MIN(dd.date_actual) AS first_purchase_date
    FROM fact_transaction ft
    INNER JOIN dim_customer dc ON ft.customer_sk = dc.customer_sk AND dc.is_current = TRUE
    INNER JOIN dim_date dd ON ft.date_sk = dd.date_sk
    INNER JOIN dim_transaction_type dtt ON ft.transaction_type_sk = dtt.transaction_type_sk
    WHERE dtt.is_refund = FALSE AND dtt.is_revenue_generating = TRUE
    GROUP BY dc.customer_id
),
monthly_revenue AS (
    SELECT 
        cc.customer_id,
        cc.cohort_month,
        DATE_TRUNC('month', dd.date_actual) AS revenue_month,
        DATEDIFF(month, cc.cohort_month, DATE_TRUNC('month', dd.date_actual)) AS months_since_first_purchase,
        SUM(ft.net_amount) AS monthly_revenue
    FROM customer_cohorts cc
    INNER JOIN dim_customer dc ON cc.customer_id = dc.customer_id AND dc.is_current = TRUE
    INNER JOIN fact_transaction ft ON dc.customer_sk = ft.customer_sk
    INNER JOIN dim_date dd ON ft.date_sk = dd.date_sk
    INNER JOIN dim_transaction_type dtt ON ft.transaction_type_sk = dtt.transaction_type_sk
    WHERE dtt.is_refund = FALSE
    GROUP BY cc.customer_id, cc.cohort_month, DATE_TRUNC('month', dd.date_actual)
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
    DATEDIFF(day, MAX(dd.date_actual), CURRENT_DATE) AS recency_days,
    CASE 
        WHEN DATEDIFF(day, MAX(dd.date_actual), CURRENT_DATE) <= 30 THEN 5
        WHEN DATEDIFF(day, MAX(dd.date_actual), CURRENT_DATE) <= 60 THEN 4
        WHEN DATEDIFF(day, MAX(dd.date_actual), CURRENT_DATE) <= 90 THEN 3
        WHEN DATEDIFF(day, MAX(dd.date_actual), CURRENT_DATE) <= 180 THEN 2
        ELSE 1
    END AS recency_score,
    
    -- Frequency (number of orders)
    COUNT(DISTINCT ft.order_id) AS frequency_count,
    NTILE(5) OVER (ORDER BY COUNT(DISTINCT ft.order_id)) AS frequency_score,
    
    -- Monetary (total spent excluding refunds)
    SUM(CASE WHEN dtt.is_refund = FALSE THEN ft.net_amount ELSE 0 END) AS monetary_value,
    NTILE(5) OVER (ORDER BY SUM(CASE WHEN dtt.is_refund = FALSE THEN ft.net_amount ELSE 0 END)) AS monetary_score
    
FROM fact_transaction ft
INNER JOIN dim_customer dc ON ft.customer_sk = dc.customer_sk AND dc.is_current = TRUE
INNER JOIN dim_date dd ON ft.date_sk = dd.date_sk
INNER JOIN dim_transaction_type dtt ON ft.transaction_type_sk = dtt.transaction_type_sk
WHERE dtt.is_revenue_generating = TRUE
GROUP BY dc.customer_id, dc.customer_name;
```

## Key Features of This Solution

### Dimensional Modeling Architecture Benefits

A well-designed star schema delivers high performance (relational) queries because of fewer table joins, and the higher likelihood of useful indexes. Also, a star schema often requires low maintenance as the data warehouse design evolves
. This schema:

- **Star Schema Design**: Central fact table surrounded by dimension tables for optimal analytical performance
- **Type 2 SCD**: Customer dimension tracks historical changes for accurate longitudinal analysis
- **Denormalized Dimensions**: 
Star schema denormalizes dimension attributes into single wide tables to improve understandability and reduce join complexity for analytic workloads


### Scalability Architecture
- **Partitioned Design**: Date-based partitioning ready for large datasets
- **Aggregate Fact Tables**: Pre-calculated customer lifecycle metrics for performance
- **Columnar Optimization**: Schema designed for modern cloud data warehouses
- **Index Strategy**: Strategic indexing for analytical query patterns

### Comprehensive CLV Calculation

LTV is the total revenue you can reasonably expect from a customer or account in a single business relationship
. The solution provides:

1. **Historical LTV**: 
Net sales as revenue metric that factors in discounts and returns, providing a more realistic picture of customers' value than gross sales

2. **Predictive LTV**: Using frequency and recency patterns
3. **Customer Segmentation**: RFM-based scoring and value tiers
4. **Cohort Analysis**: Monthly cohort tracking for retention insights

### Analytical Features
- **Refund Exclusion**: Clean separation of revenue vs. refund transactions
- **Multiple LTV Approaches**: Historical, predictive, and annualized calculations
- **Customer Health Scoring**: Recency, frequency, monetary analysis
- **Performance Optimized**: 
Analytic queries are concerned with filtering, grouping, sorting, and summarizing data. Fact data is summarized within the context of filters and groupings of the related dimension tables


This dimensional model prioritizes analytical performance and scalability while providing comprehensive customer lifetime value insights that exclude refunds and support advanced business intelligence requirements.
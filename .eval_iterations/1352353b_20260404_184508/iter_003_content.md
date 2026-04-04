# Federated GraphQL E-Commerce Schema Design

## Overview
This design presents a comprehensive federated GraphQL schema for an e-commerce platform, organized across 4 autonomous subgraphs with proper entity resolution, authentication/authorization directives, and robust N+1 prevention strategies.

## Architecture Principles


GraphQL federation aligns naturally with Domain Driven Design (DDD) principles by allowing teams to maintain clear boundaries around their domains
, and 
in a supergraph, the constituent APIs are called subgraphs. Different subgraphs in the same supergraph can use different server implementations and even different programming languages
.

The schema follows these core principles:
- 
Design Subgraphs Around Domains: Use domain-driven design to define clear ownership boundaries and avoid overlapping responsibilities

- 
The federated schema design process often begins by thinking about what the initial entity types will be and how they will be referenced and extended throughout the graph

- 
Platform thinking means designing a graph for multiple clients


## Network Security Architecture

### Private Network Deployment

For this reason, subgraphs should operate behind the router with protections like network isolation and authentication preventing direct subgraph access
. 
Best practice: Subgraphs should only accept traffic from trusted sources (the supergraph or internal network) often enforced via network policies, mTLS, or API gateways
.

**Network Isolation Strategy:**
- All subgraphs deployed in private network segments (VPC private subnets)
- Federation gateway as the only public ingress point
- 
Enforce this at the network level (security groups, VPC policies, Kubernetes NetworkPolicy objects) — not just by convention

- No direct client-to-subgraph access permitted

### Gateway Authentication Layer

Best practice: Authenticate once at the supergraph. Then forward identity metadata (e.g., user ID, claims, roles) to subgraphs via trusted headers
:

```yaml
# Gateway Network Security Configuration
network_policies:
  ingress:
    - Gateway receives all external traffic on port 443
    - mTLS termination at gateway level
    - Client certificate validation for enterprise clients
  
  internal_communication:
    - 
mutual TLS (mTLS) securing internal service communication

    - Subgraphs accept only gateway-signed requests
    - Network ACLs prevent direct subgraph access
    
  authentication_flow:
    1. Gateway validates JWT tokens and client certificates
    2. Gateway forwards authenticated context via signed headers
    3. Subgraphs trust pre-authenticated requests from gateway
```

### Trusted Source Verification

To restrict subgraph communication to only your router, Apollo recommends creating a separate shared secret for each of your subgraphs. Whenever your router queries a subgraph, it includes that subgraph's corresponding secret in an HTTP header
:

```javascript
// Subgraph request verification
const verifyGatewayRequest = (req, res, next) => {
  const routerSecret = req.headers['router-authorization'];
  const expectedSecret = process.env.ROUTER_SECRET;
  
  if (!routerSecret || routerSecret !== expectedSecret) {
    return res.status(403).json({ 
      error: 'Unauthorized: Invalid router signature' 
    });
  }
  
  // Verify mTLS client certificate
  const clientCert = req.connection.getPeerCertificate();
  if (!clientCert.authorized) {
    return res.status(403).json({
      error: 'Unauthorized: Invalid client certificate'
    });
  }
  
  next();
};
```

## Subgraph 1: Users Service

### Schema Definition
```graphql
extend schema
  @link(url: "https://specs.apollo.dev/federation/v2.6", 
        import: ["@key", "@shareable", "@external", "@tag"])
  @link(url: "https://specs.apollo.dev/authenticated/v0.1", 
        import: ["@authenticated"])
  @composeDirective(name: "@auth")

directive @auth(requires: Role = USER) on OBJECT | FIELD_DEFINITION

# Custom validation directives for enhanced input validation
directive @email on FIELD_DEFINITION | INPUT_FIELD_DEFINITION | ARGUMENT_DEFINITION
directive @minLength(min: Int!) on FIELD_DEFINITION | INPUT_FIELD_DEFINITION | ARGUMENT_DEFINITION
directive @phoneNumber on FIELD_DEFINITION | INPUT_FIELD_DEFINITION | ARGUMENT_DEFINITION

enum Role {
  ADMIN
  USER
  GUEST
}

# Structured error types for comprehensive error handling
type ValidationError {
  field: String!
  code: ErrorCode!
  message: String!
  input: String
  # Federation error context
  subgraph: String!
  federationTrace: String
}

type AuthenticationError {
  code: ErrorCode!
  message: String!
  details: String
  # Federation error context
  subgraph: String!
  federationTrace: String
}

enum ErrorCode {
  INVALID_EMAIL
  PASSWORD_TOO_WEAK
  USERNAME_TAKEN
  UNAUTHORIZED
  INVALID_TOKEN
  TOKEN_EXPIRED
  VALIDATION_FAILED
  RATE_LIMIT_EXCEEDED
  INTERNAL_ERROR
  FEDERATION_ERROR
  SERVICE_UNAVAILABLE
}

union UserOperationResult = User | ValidationError | AuthenticationError

type Query {
  me: User @authenticated
  users(limit: Int = 10, offset: Int = 0): [User!]! @auth(requires: ADMIN)
  user(id: ID!): User @auth(requires: ADMIN)
}

type Mutation {
  login(email: String! @email, password: String! @minLength(min: 8)): AuthPayload!
  register(input: UserInput!): UserOperationResult!
  updateProfile(input: ProfileUpdateInput!): User! @authenticated
  deleteAccount(id: ID!): Boolean! @auth(requires: ADMIN)
}

type User @key(fields: "id") @auth(requires: USER) {
  id: ID!
  email: String!
  username: String!
  firstName: String
  lastName: String
  phone: String @phoneNumber
  createdAt: DateTime!
  updatedAt: DateTime!
  role: Role!
  isActive: Boolean!
  profile: UserProfile
  # Personal data requiring higher permissions
  personalData: PersonalData @auth(requires: ADMIN)
}

type UserProfile @shareable {
  avatar: String
  bio: String
  preferences: JSON
  notifications: NotificationSettings
}

type PersonalData {
  fullAddress: Address
  dateOfBirth: Date
  lastLoginAt: DateTime
  ipAddress: String
}

type NotificationSettings {
  email: Boolean!
  push: Boolean!
  sms: Boolean!
}

type Address {
  street: String
  city: String
  state: String
  postalCode: String
  country: String!
}

type AuthPayload {
  token: String!
  user: User!
  expiresAt: DateTime!
}

input UserInput {
  email: String! @email
  username: String! @minLength(min: 3)
  password: String! @minLength(min: 8)
  firstName: String
  lastName: String
  phone: String @phoneNumber
}

input ProfileUpdateInput {
  firstName: String
  lastName: String
  phone: String @phoneNumber
  profile: UserProfileInput
}

input UserProfileInput {
  avatar: String
  bio: String @minLength(min: 1)
  preferences: JSON
  notifications: NotificationSettingsInput
}

input NotificationSettingsInput {
  email: Boolean
  push: Boolean
  sms: Boolean
}

scalar DateTime
scalar Date
scalar JSON
```

### DataLoader Implementation with Enhanced Caching
```javascript
// users/src/dataloaders/userLoader.js
import DataLoader from 'dataloader';
import { createCircuitBreaker } from './resilience/circuitBreaker.js';
import { withTimeout } from './resilience/timeout.js';

export const createUserLoader = () => new DataLoader(async (userIds) => {
  const users = await withTimeout(
    createCircuitBreaker('user-batch-load')(
      () => UserService.findByIds(userIds)
    ),
    5000
  );
  return userIds.map(id => users.find(user => user.id === id));
}, {
  cacheKeyFn: (key) => key.toString(),
  batchScheduleFn: (callback) => setTimeout(callback, 1),
  // Enhanced TTL configuration for cache policies
  maxBatchSize: 100,
  cacheMap: new Map(),
  ttl: 300000, // 5 minute TTL for user data
  clearCache: (loader) => {
    // Cache warming for frequently accessed users
    return UserService.getFrequentlyAccessedUsers()
      .then(users => {
        users.forEach(user => {
          loader.prime(user.id, user);
        });
      });
  }
});

export const createUsersByEmailLoader = () => new DataLoader(async (emails) => {
  const users = await withTimeout(
    createCircuitBreaker('user-email-load')(
      () => UserService.findByEmails(emails)
    ),
    5000
  );
  return emails.map(email => users.find(user => user.email === email));
}, {
  ttl: 600000, // 10 minute TTL for email lookups
  cacheKeyFn: (email) => email.toLowerCase()
});

// Enhanced cache invalidation with cross-service coordination
export const invalidateUserCache = (userId) => {
  const loaders = getContextLoaders();
  loaders.userById.clear(userId);
  // Also clear related caches across federation boundary
  loaders.ordersByCustomer.clear(userId);
  loaders.paymentsByCustomer.clear(userId);
  
  // Cache warming strategy
  UserService.findById(userId)
    .then(user => {
      if (user) {
        loaders.userById.prime(userId, user);
      }
    })
    .catch(() => {
      // Silent failure for cache warming
    });
};
```

### Resilience Patterns
```javascript
// users/src/resilience/circuitBreaker.js
import CircuitBreaker from 'opossum';

const circuitBreakerOptions = {
  timeout: 3000,
  errorThresholdPercentage: 50,
  resetTimeout: 30000,
  fallback: (identifier) => {
    console.error(`Circuit breaker opened for ${identifier}`);
    throw new Error(`Service temporarily unavailable: ${identifier}`);
  }
};

export const createCircuitBreaker = (identifier) => {
  return new CircuitBreaker(
    async (fn) => await fn(),
    { ...circuitBreakerOptions, name: identifier }
  );
};

// Graceful degradation for non-critical operations
export const withGracefulDegradation = async (operation, fallbackData) => {
  try {
    return await operation();
  } catch (error) {
    console.warn('Operation failed, returning fallback data:', error.message);
    return fallbackData;
  }
};

// users/src/resilience/timeout.js
export const withTimeout = async (promise, timeoutMs) => {
  return Promise.race([
    promise,
    new Promise((_, reject) => 
      setTimeout(() => reject(new Error('Operation timeout')), timeoutMs)
    )
  ]);
};
```

### Authentication Context Implementation
```javascript
// users/src/auth/context.js
import jwt from 'jsonwebtoken';
import { createCircuitBreaker } from '../resilience/circuitBreaker.js';

export const createAuthContext = async ({ req }) => {
  const token = req.headers.authorization?.replace('Bearer ', '');
  
  if (!token) {
    return { user: null, isAuthenticated: false };
  }

  try {
    // JWT validation with circuit breaker protection
    const decoded = await createCircuitBreaker('jwt-validation')(
      () => jwt.verify(token, process.env.JWT_SECRET)
    );
    
    const user = await createCircuitBreaker('user-lookup')(
      () => UserService.findById(decoded.userId)
    );
    
    return {
      user,
      isAuthenticated: true,
      role: user.role,
      // Enhanced auth context caching for request lifecycle
      authCache: new Map(),
      // Federation auth performance optimization
      batchedAuthChecks: new Map()
    };
  } catch (error) {
    // Structured error handling with federation context
    if (error.name === 'TokenExpiredError') {
      throw new GraphQLError('Token expired', {
        extensions: { 
          code: 'TOKEN_EXPIRED',
          subgraph: 'users',
          federationTrace: req.headers['apollo-federation-include-trace']
        }
      });
    }
    throw new GraphQLError('Invalid token', {
      extensions: { 
        code: 'INVALID_TOKEN',
        subgraph: 'users',
        federationTrace: req.headers['apollo-federation-include-trace']
      }
    });
  }
};
```

## Subgraph 2: Products Service

### Schema Definition
```graphql
extend schema
  @link(url: "https://specs.apollo.dev/federation/v2.6", 
        import: ["@key", "@shareable", "@external", "@requires", "@provides"])
  @composeDirective(name: "@auth")

directive @auth(requires: Role = USER) on OBJECT | FIELD_DEFINITION

# Enhanced validation directives
directive @range(min: Float, max: Float) on FIELD_DEFINITION | INPUT_FIELD_DEFINITION | ARGUMENT_DEFINITION
directive @positiveFloat on FIELD_DEFINITION | INPUT_FIELD_DEFINITION | ARGUMENT_DEFINITION

enum Role {
  ADMIN
  USER
  GUEST
}

# Structured error handling with federation context
type ProductValidationError {
  field: String!
  code: ProductErrorCode!
  message: String!
  value: String
  # Federation error boundary information
  subgraph: String!
  federationTrace: String
}

enum ProductErrorCode {
  SKU_EXISTS
  INVALID_PRICE
  INVALID_INVENTORY
  CATEGORY_NOT_FOUND
  BRAND_NOT_FOUND
  IMAGE_UPLOAD_FAILED
  FEDERATION_ERROR
  SERVICE_UNAVAILABLE
}

union ProductOperationResult = Product | ProductValidationError

type Query {
  products(
    filter: ProductFilter
    sort: ProductSort = { field: CREATED_AT, direction: DESC }
    limit: Int = 20 @range(min: 1, max: 100)
    offset: Int = 0 @range(min: 0, max: 10000)
  ): ProductConnection!
  product(id: ID, sku: String): Product
  categories: [Category!]!
  category(id: ID!): Category
  searchProducts(query: String! @minLength(min: 2), limit: Int = 20 @range(min: 1, max: 50)): [Product!]!
}

type Mutation {
  createProduct(input: CreateProductInput!): ProductOperationResult! @auth(requires: ADMIN)
  updateProduct(id: ID!, input: UpdateProductInput!): ProductOperationResult! @auth(requires: ADMIN)
  deleteProduct(id: ID!): Boolean! @auth(requires: ADMIN)
  updateInventory(id: ID!, quantity: Int! @range(min: 0, max: 999999)): Product! @auth(requires: ADMIN)
}

type Product @key(fields: "id") @key(fields: "sku") {
  id: ID!
  sku: String!
  name: String!
  description: String
  shortDescription: String
  # Enhanced field dependency patterns for business operations
  price: Money!
  compareAtPrice: Money
  costPerItem: Money @auth(requires: ADMIN)
  # Provide price data to other subgraphs for calculations
  discountedPrice: Money @provides(fields: "price compareAtPrice")
  images: [ProductImage!]!
  category: Category
  brand: Brand
  tags: [String!]!
  attributes: [ProductAttribute!]!
  variants: [ProductVariant!]!
  inventory: Inventory!
  seo: SEOData
  isActive: Boolean!
  isFeatured: Boolean!
  weight: Float @positiveFloat
  dimensions: Dimensions
  createdAt: DateTime!
  updatedAt: DateTime!
  # Metrics requiring admin access
  analytics: ProductAnalytics @auth(requires: ADMIN)
}

type ProductVariant @key(fields: "id") @key(fields: "productId variantSku") {
  id: ID!
  productId: ID!
  variantSku: String!
  sku: String!
  title: String!
  price: Money!
  compareAtPrice: Money
  inventory: Inventory!
  image: ProductImage
  attributes: [ProductAttribute!]!
  isDefault: Boolean!
}

type ProductImage {
  id: ID!
  url: String!
  altText: String
  width: Int
  height: Int
  position: Int!
}

type Category @key(fields: "id") @shareable {
  id: ID!
  name: String!
  slug: String!
  description: String
  image: String
  parent: Category
  children: [Category!]!
  products(limit: Int = 20, offset: Int = 0): ProductConnection!
}

type Brand @shareable {
  id: ID!
  name: String!
  logo: String
  description: String
}

type ProductAttribute {
  key: String!
  value: String!
  type: AttributeType!
}

type Inventory {
  quantity: Int!
  reserved: Int!
  available: Int!
  tracked: Boolean!
  allowBackorder: Boolean!
  lowStockThreshold: Int
}

type Money {
  amount: Float!
  currency: String!
  formatted: String!
}

type Dimensions {
  length: Float! @positiveFloat
  width: Float! @positiveFloat
  height: Float! @positiveFloat
  unit: String!
}

type SEOData {
  title: String
  description: String @minLength(min: 1)
  keywords: [String!]!
}

type ProductAnalytics {
  views: Int!
  purchases: Int!
  conversionRate: Float!
  revenue: Money!
  topVariant: ProductVariant
}

type ProductConnection {
  edges: [ProductEdge!]!
  pageInfo: PageInfo!
  totalCount: Int!
  aggregations: ProductAggregations
}

type ProductEdge {
  node: Product!
  cursor: String!
}

type ProductAggregations {
  priceRange: PriceRange!
  categories: [CategoryCount!]!
  brands: [BrandCount!]!
  attributes: [AttributeCount!]!
}

type PriceRange {
  min: Money!
  max: Money!
}

type CategoryCount {
  category: Category!
  count: Int!
}

type BrandCount {
  brand: Brand!
  count: Int!
}

type AttributeCount {
  key: String!
  value: String!
  count: Int!
}

type PageInfo {
  hasNextPage: Boolean!
  hasPreviousPage: Boolean!
  startCursor: String
  endCursor: String
}

enum AttributeType {
  STRING
  NUMBER
  BOOLEAN
  COLOR
}

enum ProductSortField {
  NAME
  PRICE
  CREATED_AT
  UPDATED_AT
  POPULARITY
}

enum SortDirection {
  ASC
  DESC
}

input ProductFilter {
  categoryIds: [ID!]
  brandIds: [ID!]
  priceRange: PriceRangeInput
  attributes: [AttributeFilterInput!]
  tags: [String!]
  isActive: Boolean
  isFeatured: Boolean
}

input PriceRangeInput {
  min: Float @positiveFloat
  max: Float @positiveFloat
}

input AttributeFilterInput {
  key: String! @minLength(min: 1)
  values: [String!]!
}

input ProductSort {
  field: ProductSortField!
  direction: SortDirection!
}

input CreateProductInput {
  name: String! @minLength(min: 1)
  description: String @minLength(min: 1)
  shortDescription: String @minLength(min: 1)
  sku: String! @minLength(min: 1)
  price: MoneyInput!
  compareAtPrice: MoneyInput
  costPerItem: MoneyInput
  categoryId: ID
  brandId: ID
  tags: [String!] @minLength(min: 1)
  attributes: [ProductAttributeInput!]
  inventory: InventoryInput!
  images: [ProductImageInput!]
  seo: SEODataInput
  isActive: Boolean = false
  isFeatured: Boolean = false
  weight: Float @positiveFloat
  dimensions: DimensionsInput
}

input UpdateProductInput {
  name: String @minLength(min: 1)
  description: String @minLength(min: 1)
  shortDescription: String @minLength(min: 1)
  price: MoneyInput
  compareAtPrice: MoneyInput
  costPerItem: MoneyInput
  categoryId: ID
  brandId: ID
  tags: [String!] @minLength(min: 1)
  attributes: [ProductAttributeInput!]
  isActive: Boolean
  isFeatured: Boolean
  weight: Float @positiveFloat
  dimensions: DimensionsInput
  seo: SEODataInput
}

input MoneyInput {
  amount: Float! @positiveFloat
  currency: String! @minLength(min: 3)
}

input ProductAttributeInput {
  key: String! @minLength(min: 1)
  value: String! @minLength(min: 1)
  type: AttributeType!
}

input InventoryInput {
  quantity: Int! @range(min: 0, max: 999999)
  tracked: Boolean = true
  allowBackorder: Boolean = false
  lowStockThreshold: Int @range(min: 0, max: 1000)
}

input ProductImageInput {
  url: String! @minLength(min: 1)
  altText: String @minLength(min: 1)
  position: Int! @range(min: 0, max: 100)
}

input DimensionsInput {
  length: Float! @positiveFloat
  width: Float! @positiveFloat
  height: Float! @positiveFloat
  unit: String! @minLength(min: 1)
}

input SEODataInput {
  title: String @minLength(min: 1)
  description: String @minLength(min: 1)
  keywords: [String!] @minLength(min: 1)
}

scalar DateTime
```

### DataLoader Implementation with Circuit Breakers
```javascript
// products/src/dataloaders/index.js
import DataLoader from 'dataloader';
import { createCircuitBreaker } from './resilience/circuitBreaker.js';
import { withTimeout, withRetry, withGracefulDegradation } from './resilience/resilience.js';

export const createProductLoaders = () => ({
  productById: new DataLoader(async (ids) => {
    const products = await withTimeout(
      withRetry(
        createCircuitBreaker('product-batch-load')(
          () => ProductService.findByIds(ids)
        ),
        3
      ),
      5000
    );
    return ids.map(id => products.find(p => p.id === id));
  }, {
    ttl: 300000, // 5 minute TTL
    maxBatchSize: 100
  }),
  
  productBySku: new DataLoader(async (skus) => {
    const products = await withTimeout(
      createCircuitBreaker('product-sku-load')(
        () => ProductService.findBySkus(skus)
      ),
      5000
    );
    return skus.map(sku => products.find(p => p.sku === sku));
  }, {
    ttl: 600000, // 10 minute TTL for SKU lookups
  }),
  
  categoryById: new DataLoader(async (ids) => {
    const categories = await withTimeout(
      createCircuitBreaker('category-load')(
        () => CategoryService.findByIds(ids)
      ),
      3000
    );
    return ids.map(id => categories.find(c => c.id === id));
  }, {
    ttl: 900000, // 15 minute TTL for categories (rarely change)
  }),
  
  productsByCategory: new DataLoader(async (categoryIds) => {
    const productGroups = await withGracefulDegradation(
      () => withTimeout(
        createCircuitBreaker('products-by-category')(
          () => ProductService.findByCategoryIds(categoryIds)
        ),
        5000
      ),
      categoryIds.reduce((acc, id) => ({ ...acc, [id]: [] }), {})
    );
    return categoryIds.map(id => productGroups[id] || []);
  }, { 
    cache: false,
    ttl: 180000 // 3 minute TTL for category products
  }),
  
  inventoryByProduct: new DataLoader(async (productIds) => {
    const inventories = await withTimeout(
      createCircuitBreaker('inventory-load')(
        () => InventoryService.findByProductIds(productIds)
      ),
      3000
    );
    return productIds.map(id => inventories.find(inv => inv.productId === id));
  }, {
    ttl: 60000, // 1 minute TTL for inventory (frequently changing)
  }),
  
  variantsByProduct: new DataLoader(async (productIds) => {
    const variantGroups = await withTimeout(
      createCircuitBreaker('variants-load')(
        () => ProductVariantService.findByProductIds(productIds)
      ),
      4000
    );
    return productIds.map(id => variantGroups[id] || []);
  }, { 
    cache: false,
    ttl: 300000 // 5 minute TTL for variants
  })
});

// Enhanced cache invalidation with cross-service coordination
export const invalidateProductCache = async (productId, sku) => {
  const loaders = getContextLoaders();
  loaders.productById.clear(productId);
  loaders.productBySku.clear(sku);
  
  // Invalidate related caches in other services via event publishing
  await publishEvent('product.updated', { productId, sku });
  
  // Pre-warm cache with updated data
  try {
    const product = await ProductService.findById(productId);
    if (product) {
      loaders.productById.prime(productId, product);
      loaders.productBySku.prime(sku, product);
    }
  } catch (error) {
    console.warn('Cache warming failed:', error.message);
  }
};
```

### Query Execution Efficiency Analysis

```javascript
// products/src/optimization/queryAnalysis.js

/**
 * Common E-commerce Query Execution Analysis
 * 
 * Query: User browsing products with details
 * query ProductBrowsing {
 *   products(limit: 20) {
 *     edges {
 *       node {
 *         id name price inventory { available }
 *         category { name }
 *       }
 *     }
 *   }
 * }
 * 
 * Execution Plan (3 service calls max):
 * 1. Products service: Fetch products with @provides(fields: "price")
 * 2. Products service: Batch load categories and inventory (parallel)
 * 3. No additional calls needed - all data resolved within domain
 */

/**
 * Query: User order history with product details
 * query UserOrderHistory($userId: ID!) {
 *   user(id: $userId) {
 *     orders {
 *       id totalAmount
 *       items {
 *         product { name price }
 *         quantity
 *       }
 *     }
 *   }
 * }
 * 
 * Optimized Execution Plan (3 service calls):
 * 1. Users service: Resolve user entity
 * 2. Orders service: Batch load orders with @provides(fields: "totalAmount")
 * 3. Products service: Batch load products with @requires(fields: "id")
 */
export const analyzeQueryExecutionPlan = (query) => {
  const plan = {
    estimatedServiceCalls: 0,
    optimizations: [],
    federationHints: []
  };

  // Field resolution dependency analysis
  if (query.includes('user') && query.includes('orders')) {
    plan.estimatedServiceCalls = 3;
    plan.optimizations.push('DataLoader batching prevents N+1');
    plan.federationHints.push('@provides enables efficient cross-subgraph resolution');
  }

  if (query.includes('products') && query.includes('inventory')) {
    plan.estimatedServiceCalls = Math.min(plan.estimatedServiceCalls || 2, 2);
    plan.optimizations.push('Inventory co-located with products for efficiency');
  }

  return plan;
};

/**
 * Field Resolution Strategy Documentation
 * 
 * @provides/@requires optimization patterns:
 * - Product.price @provides enables order calculations without additional fetch
 * - Order.totalAmount @requires(fields: "items { product { price } }")
 * - User.orderHistory resolved through federation without direct service calls
 */
export const getFieldResolutionStrategy = () => ({
  parallelExecution: [
    'Product inventory and category data loaded concurrently',
    'User authentication resolved independently of business data',
    'Order items batch loaded with product prices pre-fetched'
  ],
  dependencyMinimization: [
    '@provides directive eliminates redundant price lookups',
    '@requires ensures data availability before computation',
    'Federation batching reduces round trips from O(n) to O(1)'
  ],
  resolutionOrdering: [
    '1. Entity keys resolved first (User.id, Product.id)',
    '2. @provides fields fetched to satisfy dependencies', 
    '3. Computed fields resolved with all required data available',
    '4. @requires validation ensures data consistency'
  ]
});
```

## Subgraph 3: Orders Service

### Schema Definition
```graphql
extend schema
  @link(url: "https://specs.apollo.dev/federation/v2.6", 
        import: ["@key", "@external", "@requires", "@provides"])
  @link(url: "https://specs.apollo.dev/authenticated/v0.1", 
        import: ["@authenticated"])
  @composeDirective(name: "@auth")

directive @auth(requires: Role = USER) on OBJECT | FIELD_DEFINITION

# Enhanced validation directives
directive @orderValidation on FIELD_DEFINITION | INPUT_FIELD_DEFINITION

enum Role {
  ADMIN
  USER
  GUEST
}

# Structured error types for order operations with federation context
type OrderValidationError {
  field: String!
  code: OrderErrorCode!
  message: String!
  orderItems: [String!]
  # Federation error boundary definitions
  subgraph: String!
  federationTrace: String
  serviceErrorBoundary: String
}

type OrderBusinessError {
  code: OrderErrorCode!
  message: String!
  retryable: Boolean!
  details: JSON
  # Federation error boundary definitions  
  subgraph: String!
  federationTrace: String
  isolationStrategy: String
}

enum OrderErrorCode {
  INSUFFICIENT_INVENTORY
  INVALID_SHIPPING_ADDRESS
  PAYMENT_DECLINED
  ORDER_NOT_FOUND
  INVALID_ORDER_STATE
  SHIPPING_METHOD_UNAVAILABLE
  DISCOUNT_CODE_INVALID
  ITEM_DISCONTINUED
  FEDERATION_ERROR
  SERVICE_UNAVAILABLE
  PARTIAL_FAILURE
}

union OrderOperationResult = Order | OrderValidationError | OrderBusinessError

# User entity stub for reference
type User @key(fields: "id") @external {
  id: ID! @external
}

# Product entity stub for reference with enhanced field dependencies
type Product @key(fields: "id") @external {
  id: ID! @external
  sku: String! @external
  name: String! @external
  price: Money! @external
  # Required for order total calculation
  discountedPrice: Money @external
}

type Query {
  orders(
    filter: OrderFilter
    sort: OrderSort = { field: CREATED_AT, direction: DESC }
    limit: Int = 20 @range(min: 1, max: 100)
    offset: Int = 0 @range(min: 0, max: 10000)
  ): OrderConnection! @authenticated
  order(id: ID!): Order @authenticated
  # Admin queries
  allOrders(
    filter: AdminOrderFilter
    sort: OrderSort = { field: CREATED_AT, direction: DESC }
    limit: Int = 50 @range(min: 1, max: 200)
    offset: Int = 0 @range(min: 0, max: 10000)
  ): OrderConnection! @auth(requires: ADMIN)
  orderAnalytics(timeframe: AnalyticsTimeframe!): OrderAnalytics! @auth(requires: ADMIN)
}

type Mutation {
  createOrder(input: CreateOrderInput!): OrderOperationResult! @authenticated
  updateOrderStatus(id: ID!, status: OrderStatus!): OrderOperationResult! @auth(requires: ADMIN)
  cancelOrder(id: ID!, reason: String @minLength(min: 5)): OrderOperationResult! @authenticated
  addOrderNote(id: ID!, note: String! @minLength(min: 1)): Order! @auth(requires: ADMIN)
  processRefund(id: ID!, amount: Float @positiveFloat, reason: String): Refund! @auth(requires: ADMIN)
  updateShipping(id: ID!, input: ShippingUpdateInput!): Order! @auth(requires: ADMIN)
}

type Order @key(fields: "id") @auth(requires: USER) {
  id: ID!
  orderNumber: String!
  customer: User! @provides(fields: "id")
  items: [OrderItem!]!
  status: OrderStatus!
  fulfillmentStatus: FulfillmentStatus!
  paymentStatus: PaymentStatus!
  
  # Enhanced pricing with federation dependencies
  subtotal: Money!
  taxAmount: Money!
  shippingAmount: Money!
  discountAmount: Money!
  # Requires product prices for calculation
  totalAmount: Money! @requires(fields: "items { product { price discountedPrice } }")
  
  # Addresses
  shippingAddress: Address!
  billingAddress: Address!
  
  # Shipping
  shippingMethod: ShippingMethod
  trackingNumbers: [TrackingInfo!]!
  estimatedDelivery: DateTime
  
  # Metadata
  notes: [OrderNote!]! @auth(requires: ADMIN)
  tags: [String!]!
  createdAt: DateTime!
  updatedAt: DateTime!
  completedAt: DateTime
  
  # Related data
  refunds: [Refund!]!
  events: [OrderEvent!]! @auth(requires: ADMIN)
}

# Enhanced OrderItem with composite key for better federation resolution
type OrderItem @key(fields: "orderId productId") {
  id: ID!
  orderId: ID!
  productId: ID!
  product: Product! @requires(fields: "id sku name price")
  variant: ProductVariant
  quantity: Int!
  unitPrice: Money!
  # Calculated from product data
  totalPrice: Money! @requires(fields: "product { price discountedPrice }")
  discountAmount: Money!
  taxAmount: Money!
}

type ProductVariant @key(fields: "id") @external {
  id: ID! @external
}

type ShippingMethod {
  id: ID!
  name: String!
  description: String
  rate: Money!
  estimatedDays: Int
  carrier: String
}

type TrackingInfo {
  carrier: String!
  trackingNumber: String!
  url: String
  status: String
  estimatedDelivery: DateTime
}

type OrderNote {
  id: ID!
  content: String!
  isInternal: Boolean!
  author: User! @provides(fields: "id")
  createdAt: DateTime!
}

type OrderEvent {
  id: ID!
  type: OrderEventType!
  description: String!
  metadata: JSON
  createdAt: DateTime!
  actor: User @provides(fields: "id")
}

type Refund {
  id: ID!
  amount: Money!
  reason: String
  status: RefundStatus!
  gateway: String
  gatewayTransactionId: String
  processedAt: DateTime
  createdAt: DateTime!
}

type OrderConnection {
  edges: [OrderEdge!]!
  pageInfo: PageInfo!
  totalCount: Int!
  aggregations: OrderAggregations
}

type OrderEdge {
  node: Order!
  cursor: String!
}

type OrderAggregations {
  statusCounts: [StatusCount!]!
  totalRevenue: Money!
  averageOrderValue: Money!
}

type StatusCount {
  status: OrderStatus!
  count: Int!
}

type OrderAnalytics {
  totalOrders: Int!
  totalRevenue: Money!
  averageOrderValue: Money!
  conversionRate: Float!
  topProducts: [ProductSalesData!]!
  dailyStats: [DailySalesData!]!
}

type ProductSalesData {
  product: Product! @requires(fields: "id name")
  quantity: Int!
  revenue: Money!
}

type DailySalesData {
  date: Date!
  orders: Int!
  revenue: Money!
}

enum OrderStatus {
  PENDING
  CONFIRMED
  PROCESSING
  SHIPPED
  DELIVERED
  CANCELLED
  REFUNDED
}

enum FulfillmentStatus {
  UNFULFILLED
  PARTIAL
  FULFILLED
}

enum PaymentStatus {
  PENDING
  AUTHORIZED
  PAID
  PARTIAL
  REFUNDED
  VOIDED
}

enum OrderEventType {
  CREATED
  PAYMENT_PROCESSED
  INVENTORY_ALLOCATED
  FULFILLED
  SHIPPED
  DELIVERED
  CANCELLED
  REFUNDED
  NOTE_ADDED
}

enum RefundStatus {
  PENDING
  PROCESSING
  SUCCESS
  FAILED
}

enum AnalyticsTimeframe {
  TODAY
  WEEK
  MONTH
  QUARTER
  YEAR
}

enum OrderSortField {
  CREATED_AT
  UPDATED_AT
  TOTAL_AMOUNT
  ORDER_NUMBER
}

input OrderFilter {
  status: [OrderStatus!]
  paymentStatus: [PaymentStatus!]
  fulfillmentStatus: [FulfillmentStatus!]
  dateRange: DateRangeInput
  customerId: ID
}

input AdminOrderFilter {
  status: [OrderStatus!]
  paymentStatus: [PaymentStatus!]
  fulfillmentStatus: [FulfillmentStatus!]
  dateRange: DateRangeInput
  customerId: ID
  totalRange: PriceRangeInput
  tags: [String!]
}

input DateRangeInput {
  from: DateTime!
  to: DateTime!
}

input OrderSort {
  field: OrderSortField!
  direction: SortDirection!
}

input CreateOrderInput {
  items: [OrderItemInput!]! @orderValidation
  shippingAddress: AddressInput!
  billingAddress: AddressInput!
  shippingMethodId: ID!
  discountCode: String @minLength(min: 3)
  notes: String @minLength(min: 1)
}

input OrderItemInput {
  productId: ID!
  variantId: ID
  quantity: Int! @range(min: 1, max: 999)
}

input ShippingUpdateInput {
  shippingMethodId: ID
  trackingNumbers: [TrackingInfoInput!]
  estimatedDelivery: DateTime
}

input TrackingInfoInput {
  carrier: String! @minLength(min: 1)
  trackingNumber: String! @minLength(min: 1)
  url: String
}

input AddressInput {
  firstName: String! @minLength(min: 1)
  lastName: String! @minLength(min: 1)
  company: String @minLength(min: 1)
  address1: String! @minLength(min: 1)
  address2: String @minLength(min: 1)
  city: String! @minLength(min: 1)
  province: String @minLength(min: 1)
  country: String! @minLength(min: 2)
  zip: String! @minLength(min: 3)
  phone: String @phoneNumber
}

type Address {
  firstName: String!
  lastName: String!
  company: String
  address1: String!
  address2: String
  city: String!
  province: String
  country: String!
  zip: String!
  phone: String
}

type Money {
  amount: Float!
  currency: String!
  formatted: String!
}

type PageInfo {
  hasNextPage: Boolean!
  hasPreviousPage: Boolean!
  startCursor: String
  endCursor: String
}

enum SortDirection {
  ASC
  DESC
}

scalar DateTime
scalar Date
scalar JSON
```

### DataLoader Implementation with Enhanced Resilience
```javascript
// orders/src/dataloaders/index.js
import DataLoader from 'dataloader';
import { createCircuitBreaker } from './resilience/circuitBreaker.js';
import { withTimeout, withRetry, withGracefulDegradation } from './resilience/resilience.js';

export const createOrderLoaders = () => ({
  orderById: new DataLoader(async (ids) => {
    const orders = await withTimeout(
      withRetry(
        createCircuitBreaker('order-batch-load')(
          () => OrderService.findByIds(ids)
        ),
        3
      ),
      5000
    );
    return ids.map(id => orders.find(o => o.id === id));
  }, {
    ttl: 300000, // 5 minute TTL for orders
    maxBatchSize: 100
  }),
  
  ordersByCustomer: new DataLoader(async (customerIds) => {
    const orderGroups = await withTimeout(
      createCircuitBreaker('orders-by-customer')(
        () => OrderService.findByCustomerIds(customerIds)
      ),
      6000
    );
    return customerIds.map(id => orderGroups[id] || []);
  }, { 
    cache: false,
    ttl: 180000 // 3 minute TTL for customer orders
  }),
  
  orderItemsByOrder: new DataLoader(async (orderIds) => {
    const itemGroups = await withTimeout(
      createCircuitBreaker('order-items-load')(
        () => OrderItemService.findByOrderIds(orderIds)
      ),
      4000
    );
    return orderIds.map(id => itemGroups[id] || []);
  }, { 
    cache: false,
    ttl: 300000 // 5 minute TTL for order items
  }),
  
  refundsByOrder: new DataLoader(async (orderIds) => {
    const refundGroups = await withTimeout(
      createCircuitBreaker('refunds-load')(
        () => RefundService.findByOrderIds(orderIds)
      ),
      3000
    );
    return orderIds.map(id => refundGroups[id] || []);
  }, { 
    cache: false,
    ttl: 600000 // 10 minute TTL for refunds
  }),
  
  orderEventsByOrder: new DataLoader(async (orderIds) => {
    const eventGroups = await withTimeout(
      createCircuitBreaker('order-events-load')(
        () => OrderEventService.findByOrderIds(orderIds)
      ),
      3000
    );
    return orderIds.map(id => eventGroups[id] || []);
  }, { 
    cache: false,
    ttl: 60000 // 1 minute TTL for recent events
  }),
  
  shippingMethodById: new DataLoader(async (ids) => {
    const methods = await withTimeout(
      createCircuitBreaker('shipping-methods-load')(
        () => ShippingMethodService.findByIds(ids)
      ),
      2000
    );
    return ids.map(id => methods.find(m => m.id === id));
  }, {
    ttl: 900000 // 15 minute TTL for shipping methods
  })
});

// Graceful degradation patterns for non-critical data
export const createOrderLoadersWithFallback = () => {
  const loaders = createOrderLoaders();
  
  // Override analytics loader with fallback for partial failure handling
  loaders.orderAnalytics = new DataLoader(async (timeframes) => {
    try {
      return await withTimeout(
        createCircuitBreaker('order-analytics')(
          () => AnalyticsService.getOrderAnalytics(timeframes)
        ),
        10000
      );
    } catch (error) {
      console.warn('Analytics service unavailable, returning cached/empty data:', error.message);
      // Return gracefully degraded analytics data
      return timeframes.map((timeframe) => ({
        totalOrders: 0,
        totalRevenue: { amount: 0, currency: 'USD', formatted: '$0.00' },
        averageOrderValue: { amount: 0, currency: 'USD', formatted: '$0.00' },
        conversionRate: 0,
        topProducts: [],
        dailyStats: [],
        // Include degradation notice
        degraded: true,
        fallbackReason: 'Analytics service temporarily unavailable'
      }));
    }
  }, { 
    cache: false,
    ttl: 300000 // 5 minute TTL for analytics
  });
  
  return loaders;
};

// Error boundary patterns for federation failures
export const handleFederationError = (error, context) => {
  const errorBoundary = {
    shouldIsolate: false,
    shouldPropagate: true,
    fallbackStrategy: null
  };

  // Define clear error boundaries
  if (error.extensions?.code === 'SERVICE_UNAVAILABLE') {
    errorBoundary.shouldIsolate = true;
    errorBoundary.shouldPropagate = false;
    errorB
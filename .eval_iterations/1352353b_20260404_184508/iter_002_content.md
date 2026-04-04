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
}

type AuthenticationError {
  code: ErrorCode!
  message: String!
  details: String
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

### DataLoader Implementation
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
  batchScheduleFn: (callback) => setTimeout(callback, 1)
});

export const createUsersByEmailLoader = () => new DataLoader(async (emails) => {
  const users = await withTimeout(
    createCircuitBreaker('user-email-load')(
      () => UserService.findByEmails(emails)
    ),
    5000
  );
  return emails.map(email => users.find(user => user.email === email));
});

// Cache invalidation strategy
export const invalidateUserCache = (userId) => {
  const loaders = getContextLoaders();
  loaders.userById.clear(userId);
  // Also clear related caches
  loaders.ordersByCustomer.clear(userId);
  loaders.paymentsByCustomer.clear(userId);
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
      // Cache auth context for request lifecycle
      authCache: new Map()
    };
  } catch (error) {
    // Structured error handling for auth failures
    if (error.name === 'TokenExpiredError') {
      throw new GraphQLError('Token expired', {
        extensions: { code: 'TOKEN_EXPIRED' }
      });
    }
    throw new GraphQLError('Invalid token', {
      extensions: { code: 'INVALID_TOKEN' }
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

# Structured error handling
type ProductValidationError {
  field: String!
  code: ProductErrorCode!
  message: String!
  value: String
}

enum ProductErrorCode {
  SKU_EXISTS
  INVALID_PRICE
  INVALID_INVENTORY
  CATEGORY_NOT_FOUND
  BRAND_NOT_FOUND
  IMAGE_UPLOAD_FAILED
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
  price: Money!
  compareAtPrice: Money
  costPerItem: Money @auth(requires: ADMIN)
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

type ProductVariant @key(fields: "id") {
  id: ID!
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
import { withTimeout, withRetry } from './resilience/resilience.js';

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
  }),
  
  productBySku: new DataLoader(async (skus) => {
    const products = await withTimeout(
      createCircuitBreaker('product-sku-load')(
        () => ProductService.findBySkus(skus)
      ),
      5000
    );
    return skus.map(sku => products.find(p => p.sku === sku));
  }),
  
  categoryById: new DataLoader(async (ids) => {
    const categories = await withTimeout(
      createCircuitBreaker('category-load')(
        () => CategoryService.findByIds(ids)
      ),
      3000
    );
    return ids.map(id => categories.find(c => c.id === id));
  }),
  
  productsByCategory: new DataLoader(async (categoryIds) => {
    const productGroups = await withTimeout(
      createCircuitBreaker('products-by-category')(
        () => ProductService.findByCategoryIds(categoryIds)
      ),
      5000
    );
    return categoryIds.map(id => productGroups[id] || []);
  }, { cache: false }),
  
  inventoryByProduct: new DataLoader(async (productIds) => {
    const inventories = await withTimeout(
      createCircuitBreaker('inventory-load')(
        () => InventoryService.findByProductIds(productIds)
      ),
      3000
    );
    return productIds.map(id => inventories.find(inv => inv.productId === id));
  }),
  
  variantsByProduct: new DataLoader(async (productIds) => {
    const variantGroups = await withTimeout(
      createCircuitBreaker('variants-load')(
        () => ProductVariantService.findByProductIds(productIds)
      ),
      4000
    );
    return productIds.map(id => variantGroups[id] || []);
  }, { cache: false })
});

// Enhanced cache invalidation with cross-service coordination
export const invalidateProductCache = async (productId, sku) => {
  const loaders = getContextLoaders();
  loaders.productById.clear(productId);
  loaders.productBySku.clear(sku);
  
  // Invalidate related caches in other services via event publishing
  await publishEvent('product.updated', { productId, sku });
};
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

# Structured error types for order operations
type OrderValidationError {
  field: String!
  code: OrderErrorCode!
  message: String!
  orderItems: [String!]
}

type OrderBusinessError {
  code: OrderErrorCode!
  message: String!
  retryable: Boolean!
  details: JSON
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
}

union OrderOperationResult = Order | OrderValidationError | OrderBusinessError

# User entity stub for reference
type User @key(fields: "id") @external {
  id: ID! @external
}

# Product entity stub for reference  
type Product @key(fields: "id") @external {
  id: ID! @external
  sku: String! @external
  name: String! @external
  price: Money! @external
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
  
  # Pricing
  subtotal: Money!
  taxAmount: Money!
  shippingAmount: Money!
  discountAmount: Money!
  totalAmount: Money!
  
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
  totalPrice: Money!
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
import { withTimeout, withRetry } from './resilience/resilience.js';

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
  }),
  
  ordersByCustomer: new DataLoader(async (customerIds) => {
    const orderGroups = await withTimeout(
      createCircuitBreaker('orders-by-customer')(
        () => OrderService.findByCustomerIds(customerIds)
      ),
      6000
    );
    return customerIds.map(id => orderGroups[id] || []);
  }, { cache: false }),
  
  orderItemsByOrder: new DataLoader(async (orderIds) => {
    const itemGroups = await withTimeout(
      createCircuitBreaker('order-items-load')(
        () => OrderItemService.findByOrderIds(orderIds)
      ),
      4000
    );
    return orderIds.map(id => itemGroups[id] || []);
  }, { cache: false }),
  
  refundsByOrder: new DataLoader(async (orderIds) => {
    const refundGroups = await withTimeout(
      createCircuitBreaker('refunds-load')(
        () => RefundService.findByOrderIds(orderIds)
      ),
      3000
    );
    return orderIds.map(id => refundGroups[id] || []);
  }, { cache: false }),
  
  orderEventsByOrder: new DataLoader(async (orderIds) => {
    const eventGroups = await withTimeout(
      createCircuitBreaker('order-events-load')(
        () => OrderEventService.findByOrderIds(orderIds)
      ),
      3000
    );
    return orderIds.map(id => eventGroups[id] || []);
  }, { cache: false }),
  
  shippingMethodById: new DataLoader(async (ids) => {
    const methods = await withTimeout(
      createCircuitBreaker('shipping-methods-load')(
        () => ShippingMethodService.findByIds(ids)
      ),
      2000
    );
    return ids.map(id => methods.find(m => m.id === id));
  })
});

// Graceful degradation patterns for non-critical data
export const createOrderLoadersWithFallback = () => {
  const loaders = createOrderLoaders();
  
  // Override analytics loader with fallback
  loaders.orderAnalytics = new DataLoader(async (timeframes) => {
    try {
      return await withTimeout(
        createCircuitBreaker('order-analytics')(
          () => AnalyticsService.getOrderAnalytics(timeframes)
        ),
        10000
      );
    } catch (error) {
      console.warn('Analytics service unavailable, returning empty data:', error.message);
      // Return empty analytics data instead of failing
      return timeframes.map(() => ({
        totalOrders: 0,
        totalRevenue: { amount: 0, currency: 'USD', formatted: '$0.00' },
        averageOrderValue: { amount: 0, currency: 'USD', formatted: '$0.00' },
        conversionRate: 0,
        topProducts: [],
        dailyStats: []
      }));
    }
  }, { cache: false });
  
  return loaders;
};
```

## Subgraph 4: Payments Service

### Schema Definition
```graphql
extend schema
  @link(url: "https://specs.apollo.dev/federation/v2.6", 
        import: ["@key", "@external", "@requires"])
  @link(url: "https://specs.apollo.dev/authenticated/v0.1", 
        import: ["@authenticated"])
  @composeDirective(name: "@auth")

directive @auth(requires: Role = USER) on OBJECT | FIELD_DEFINITION

# Enhanced validation directives for payment security
directive @creditCard on FIELD_DEFINITION | INPUT_FIELD_DEFINITION
directive @currency on FIELD_DEFINITION | INPUT_FIELD_DEFINITION
directive @paymentValidation on FIELD_DEFINITION | INPUT_FIELD_DEFINITION

enum Role {
  ADMIN
  USER
  GUEST
}

# Comprehensive error handling for payment operations
type PaymentValidationError {
  field: String!
  code: PaymentErrorCode!
  message: String!
  details: JSON
}

type PaymentSecurityError {
  code: PaymentErrorCode!
  message: String!
  fraudScore: Float
  blocked: Boolean!
}

type PaymentBusinessError {
  code: PaymentErrorCode!
  message: String!
  retryable: Boolean!
  gatewayCode: String
}

enum PaymentErrorCode {
  INVALID_PAYMENT_METHOD
  INSUFFICIENT_FUNDS
  PAYMENT_DECLINED
  FRAUD_DETECTED
  GATEWAY_ERROR
  INVALID_AMOUNT
  CURRENCY_NOT_SUPPORTED
  PAYMENT_ALREADY_PROCESSED
  REFUND_FAILED
  AUTHORIZATION_EXPIRED
}

union PaymentOperationResult = Payment | PaymentValidationError | PaymentSecurityError | PaymentBusinessError
union PaymentIntentResult = PaymentIntent | PaymentValidationError | PaymentBusinessError

# Entity stubs for reference
type User @key(fields: "id") @external {
  id: ID! @external
}

type Order @key(fields: "id") @external {
  id: ID! @external
  orderNumber: String! @external
  totalAmount: Money! @external
  customer: User! @external @requires(fields: "id")
}

type Query {
  payment(id: ID!): Payment @authenticated
  payments(
    filter: PaymentFilter
    sort: PaymentSort = { field: CREATED_AT, direction: DESC }
    limit: Int = 20 @range(min: 1, max: 100)
    offset: Int = 0 @range(min: 0, max: 10000)
  ): PaymentConnection! @authenticated
  
  # Admin queries
  allPayments(
    filter: AdminPaymentFilter
    sort: PaymentSort = { field: CREATED_AT, direction: DESC }
    limit: Int = 50 @range(min: 1, max: 200)
    offset: Int = 0 @range(min: 0, max: 10000)
  ): PaymentConnection! @auth(requires: ADMIN)
  
  paymentMethods: [PaymentMethod!]! @authenticated
  paymentAnalytics(timeframe: AnalyticsTimeframe!): PaymentAnalytics! @auth(requires: ADMIN)
  fraudAlerts(limit: Int = 20 @range(min: 1, max: 100)): [FraudAlert!]! @auth(requires: ADMIN)
}

type Mutation {
  createPaymentIntent(input: PaymentIntentInput!): PaymentIntentResult! @authenticated
  confirmPayment(paymentIntentId: ID!, paymentMethodId: ID!): PaymentOperationResult! @authenticated
  processRefund(paymentId: ID!, amount: Float @positiveFloat, reason: String @minLength(min: 5)): PaymentOperationResult! @auth(requires: ADMIN)
  captureAuthorization(paymentId: ID!, amount: Float @positiveFloat): PaymentOperationResult! @auth(requires: ADMIN)
  voidAuthorization(paymentId: ID!): PaymentOperationResult! @auth(requires: ADMIN)
  
  # Payment methods management
  savePaymentMethod(input: PaymentMethodInput!): PaymentOperationResult! @authenticated
  removePaymentMethod(id: ID!): Boolean! @authenticated
  updatePaymentMethod(id: ID!, input: PaymentMethodUpdateInput!): PaymentOperationResult! @authenticated
  
  # Fraud management
  markFraudulent(paymentId: ID!, reason: String! @minLength(min: 5)): PaymentOperationResult! @auth(requires: ADMIN)
  approveFraudAlert(alertId: ID!): FraudAlert! @auth(requires: ADMIN)
}

type Payment @key(fields: "id") @auth(requires: USER) {
  id: ID!
  order: Order! @requires(fields: "id orderNumber totalAmount")
  amount: Money!
  currency: String! @currency
  status: PaymentStatus!
  method: PaymentMethod!
  gateway: PaymentGateway!
  
  # Gateway details
  gatewayTransactionId: String
  gatewayResponse: JSON @auth(requires: ADMIN)
  
  # Authorization/Capture tracking
  authorizedAmount: Money
  capturedAmount: Money!
  refundedAmount: Money!
  
  # Security
  fraudScore: Float @auth(requires: ADMIN)
  fraudFlags: [FraudFlag!]! @auth(requires: ADMIN)
  riskLevel: RiskLevel!
  
  # Billing
  billingAddress: Address!
  
  # Metadata
  description: String
  metadata: JSON
  fees: [PaymentFee!]! @auth(requires: ADMIN)
  
  # Timestamps
  authorizedAt: DateTime
  capturedAt: DateTime
  createdAt: DateTime!
  updatedAt: DateTime!
  
  # Related data
  refunds: [PaymentRefund!]!
  events: [PaymentEvent!]! @auth(requires: ADMIN)
}

type PaymentIntent {
  id: ID!
  clientSecret: String!
  amount: Money!
  currency: String! @currency
  status: PaymentIntentStatus!
  order: Order! @requires(fields: "id")
  availablePaymentMethods: [PaymentMethod!]!
  expiresAt: DateTime!
  createdAt: DateTime!
}

type SavedPaymentMethod @key(fields: "id") @auth(requires: USER) {
  id: ID!
  customer: User! @requires(fields: "id")
  type: PaymentMethodType!
  last4: String! @creditCard
  brand: String
  expiryMonth: Int @range(min: 1, max: 12)
  expiryYear: Int @range(min: 2024, max: 2050)
  billingAddress: Address
  isDefault: Boolean!
  createdAt: DateTime!
}

type PaymentMethod {
  id: ID!
  name: String!
  type: PaymentMethodType!
  enabled: Boolean!
  supportedCurrencies: [String!]! @currency
  processingFee: ProcessingFee!
  minimumAmount: Money
  maximumAmount: Money
  countries: [String!]!
}

type PaymentGateway {
  id: ID!
  name: String!
  type: String!
  enabled: Boolean!
  supportedMethods: [PaymentMethodType!]!
  supportedCurrencies: [String!]! @currency
}

type PaymentRefund {
  id: ID!
  amount: Money!
  reason: String
  status: RefundStatus!
  gatewayRefundId: String
  processedAt: DateTime
  createdAt: DateTime!
}

type PaymentEvent {
  id: ID!
  type: PaymentEventType!
  amount: Money
  description: String!
  gatewayResponse: JSON
  createdAt: DateTime!
}

type PaymentFee {
  type: FeeType!
  amount: Money!
  description: String
}

type FraudAlert {
  id: ID!
  payment: Payment! @requires(fields: "id")
  rule: String!
  score: Float! @range(min: 0.0, max: 1.0)
  reason: String!
  status: FraudAlertStatus!
  reviewedBy: User @requires(fields: "id")
  reviewedAt: DateTime
  createdAt: DateTime!
}

type FraudFlag {
  type: FraudFlagType!
  severity: FraudSeverity!
  description: String!
}

type ProcessingFee {
  fixed: Money
  percentage: Float! @range(min: 0.0, max: 100.0)
}

type PaymentConnection {
  edges: [PaymentEdge!]!
  pageInfo: PageInfo!
  totalCount: Int!
  aggregations: PaymentAggregations
}

type PaymentEdge {
  node: Payment!
  cursor: String!
}

type PaymentAggregations {
  statusCounts: [PaymentStatusCount!]!
  totalVolume: Money!
  totalFees: Money!
  averageAmount: Money!
}

type PaymentStatusCount {
  status: PaymentStatus!
  count: Int!
  amount: Money!
}

type PaymentAnalytics {
  totalVolume: Money!
  totalFees: Money!
  successRate: Float! @range(min: 0.0, max: 1.0)
  fraudRate: Float! @range(min: 0.0, max: 1.0)
  averageAmount: Money!
  methodBreakdown: [PaymentMethodStats!]!
  dailyVolume: [DailyVolumeData!]!
  topDeclineReasons: [DeclineReasonData!]!
}

type PaymentMethodStats {
  method: PaymentMethodType!
  volume: Money!
  count: Int!
  successRate: Float! @range(min: 0.0, max: 1.0)
}

type DailyVolumeData {
  date: Date!
  volume: Money!
  count: Int!
  successRate: Float! @range(min: 0.0, max: 1.0)
}

type DeclineReasonData {
  reason: String!
  count: Int!
  percentage: Float! @range(min: 0.0, max: 100.0)
}

enum PaymentStatus {
  PENDING
  AUTHORIZED
  CAPTURED
  PARTIALLY_CAPTURED
  PARTIALLY_REFUNDED
  REFUNDED
  VOIDED
  FAILED
  CANCELLED
}

enum PaymentIntentStatus {
  REQUIRES_PAYMENT_METHOD
  REQUIRES_CONFIRMATION
  REQUIRES_ACTION
  PROCESSING
  SUCCEEDED
  CANCELLED
}

enum PaymentMethodType {
  CREDIT_CARD
  DEBIT_CARD
  PAYPAL
  APPLE_PAY
  GOOGLE_PAY
  BANK_TRANSFER
  BUY_NOW_PAY_LATER
  CRYPTOCURRENCY
  GIFT_CARD
}

enum RefundStatus {
  PENDING
  PROCESSING
  SUCCESS
  FAILED
  CANCELLED
}

enum PaymentEventType {
  AUTHORIZATION_REQUESTED
  AUTHORIZED
  AUTHORIZATION_FAILED
  CAPTURE_REQUESTED
  CAPTURED
  CAPTURE_FAILED
  REFUND_REQUESTED
  REFUNDED
  REFUND_FAILED
  VOIDED
  CHARGEBACK_CREATED
  CHARGEBACK_RESOLVED
}

enum RiskLevel {
  LOW
  MEDIUM
  HIGH
  BLOCKED
}

enum FraudFlagType {
  VELOCITY
  GEOLOCATION
  DEVICE_FINGERPRINT
  BIN_CHECK
  CVV_MISMATCH
  AVS_MISMATCH
  BLACKLIST
  SUSPICIOUS_PATTERN
}

enum FraudSeverity {
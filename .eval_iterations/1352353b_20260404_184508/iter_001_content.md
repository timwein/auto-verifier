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

enum Role {
  ADMIN
  USER
  GUEST
}

type Query {
  me: User @authenticated
  users(limit: Int = 10, offset: Int = 0): [User!]! @auth(requires: ADMIN)
  user(id: ID!): User @auth(requires: ADMIN)
}

type Mutation {
  login(email: String!, password: String!): AuthPayload!
  register(input: UserInput!): AuthPayload!
  updateProfile(input: ProfileUpdateInput!): User! @authenticated
  deleteAccount(id: ID!): Boolean! @auth(requires: ADMIN)
}

type User @key(fields: "id") @auth(requires: USER) {
  id: ID!
  email: String!
  username: String!
  firstName: String
  lastName: String
  phone: String
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
  email: String!
  username: String!
  password: String!
  firstName: String
  lastName: String
  phone: String
}

input ProfileUpdateInput {
  firstName: String
  lastName: String
  phone: String
  profile: UserProfileInput
}

input UserProfileInput {
  avatar: String
  bio: String
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

export const createUserLoader = () => new DataLoader(async (userIds) => {
  const users = await UserService.findByIds(userIds);
  return userIds.map(id => users.find(user => user.id === id));
}, {
  cacheKeyFn: (key) => key.toString(),
  batchScheduleFn: (callback) => setTimeout(callback, 1)
});

export const createUsersByEmailLoader = () => new DataLoader(async (emails) => {
  const users = await UserService.findByEmails(emails);
  return emails.map(email => users.find(user => user.email === email));
});
```

## Subgraph 2: Products Service

### Schema Definition
```graphql
extend schema
  @link(url: "https://specs.apollo.dev/federation/v2.6", 
        import: ["@key", "@shareable", "@external", "@requires", "@provides"])
  @composeDirective(name: "@auth")

directive @auth(requires: Role = USER) on OBJECT | FIELD_DEFINITION

enum Role {
  ADMIN
  USER
  GUEST
}

type Query {
  products(
    filter: ProductFilter
    sort: ProductSort = { field: CREATED_AT, direction: DESC }
    limit: Int = 20
    offset: Int = 0
  ): ProductConnection!
  product(id: ID, sku: String): Product
  categories: [Category!]!
  category(id: ID!): Category
  searchProducts(query: String!, limit: Int = 20): [Product!]!
}

type Mutation {
  createProduct(input: CreateProductInput!): Product! @auth(requires: ADMIN)
  updateProduct(id: ID!, input: UpdateProductInput!): Product! @auth(requires: ADMIN)
  deleteProduct(id: ID!): Boolean! @auth(requires: ADMIN)
  updateInventory(id: ID!, quantity: Int!): Product! @auth(requires: ADMIN)
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
  weight: Float
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
  length: Float!
  width: Float!
  height: Float!
  unit: String!
}

type SEOData {
  title: String
  description: String
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
  min: Float
  max: Float
}

input AttributeFilterInput {
  key: String!
  values: [String!]!
}

input ProductSort {
  field: ProductSortField!
  direction: SortDirection!
}

input CreateProductInput {
  name: String!
  description: String
  shortDescription: String
  sku: String!
  price: MoneyInput!
  compareAtPrice: MoneyInput
  costPerItem: MoneyInput
  categoryId: ID
  brandId: ID
  tags: [String!]
  attributes: [ProductAttributeInput!]
  inventory: InventoryInput!
  images: [ProductImageInput!]
  seo: SEODataInput
  isActive: Boolean = false
  isFeatured: Boolean = false
  weight: Float
  dimensions: DimensionsInput
}

input UpdateProductInput {
  name: String
  description: String
  shortDescription: String
  price: MoneyInput
  compareAtPrice: MoneyInput
  costPerItem: MoneyInput
  categoryId: ID
  brandId: ID
  tags: [String!]
  attributes: [ProductAttributeInput!]
  isActive: Boolean
  isFeatured: Boolean
  weight: Float
  dimensions: DimensionsInput
  seo: SEODataInput
}

input MoneyInput {
  amount: Float!
  currency: String!
}

input ProductAttributeInput {
  key: String!
  value: String!
  type: AttributeType!
}

input InventoryInput {
  quantity: Int!
  tracked: Boolean = true
  allowBackorder: Boolean = false
  lowStockThreshold: Int
}

input ProductImageInput {
  url: String!
  altText: String
  position: Int!
}

input DimensionsInput {
  length: Float!
  width: Float!
  height: Float!
  unit: String!
}

input SEODataInput {
  title: String
  description: String
  keywords: [String!]
}

scalar DateTime
```

### DataLoader Implementation
```javascript
// products/src/dataloaders/index.js
import DataLoader from 'dataloader';

export const createProductLoaders = () => ({
  productById: new DataLoader(async (ids) => {
    const products = await ProductService.findByIds(ids);
    return ids.map(id => products.find(p => p.id === id));
  }),
  
  productBySku: new DataLoader(async (skus) => {
    const products = await ProductService.findBySkus(skus);
    return skus.map(sku => products.find(p => p.sku === sku));
  }),
  
  categoryById: new DataLoader(async (ids) => {
    const categories = await CategoryService.findByIds(ids);
    return ids.map(id => categories.find(c => c.id === id));
  }),
  
  productsByCategory: new DataLoader(async (categoryIds) => {
    const productGroups = await ProductService.findByCategoryIds(categoryIds);
    return categoryIds.map(id => productGroups[id] || []);
  }, { cache: false }),
  
  inventoryByProduct: new DataLoader(async (productIds) => {
    const inventories = await InventoryService.findByProductIds(productIds);
    return productIds.map(id => inventories.find(inv => inv.productId === id));
  }),
  
  variantsByProduct: new DataLoader(async (productIds) => {
    const variantGroups = await ProductVariantService.findByProductIds(productIds);
    return productIds.map(id => variantGroups[id] || []);
  }, { cache: false })
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

enum Role {
  ADMIN
  USER
  GUEST
}

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
    limit: Int = 20
    offset: Int = 0
  ): OrderConnection! @authenticated
  order(id: ID!): Order @authenticated
  # Admin queries
  allOrders(
    filter: AdminOrderFilter
    sort: OrderSort = { field: CREATED_AT, direction: DESC }
    limit: Int = 50
    offset: Int = 0
  ): OrderConnection! @auth(requires: ADMIN)
  orderAnalytics(timeframe: AnalyticsTimeframe!): OrderAnalytics! @auth(requires: ADMIN)
}

type Mutation {
  createOrder(input: CreateOrderInput!): Order! @authenticated
  updateOrderStatus(id: ID!, status: OrderStatus!): Order! @auth(requires: ADMIN)
  cancelOrder(id: ID!, reason: String): Order! @authenticated
  addOrderNote(id: ID!, note: String!): Order! @auth(requires: ADMIN)
  processRefund(id: ID!, amount: Float, reason: String): Refund! @auth(requires: ADMIN)
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

type OrderItem {
  id: ID!
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
  items: [OrderItemInput!]!
  shippingAddress: AddressInput!
  billingAddress: AddressInput!
  shippingMethodId: ID!
  discountCode: String
  notes: String
}

input OrderItemInput {
  productId: ID!
  variantId: ID
  quantity: Int!
}

input ShippingUpdateInput {
  shippingMethodId: ID
  trackingNumbers: [TrackingInfoInput!]
  estimatedDelivery: DateTime
}

input TrackingInfoInput {
  carrier: String!
  trackingNumber: String!
  url: String
}

input AddressInput {
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

### DataLoader Implementation
```javascript
// orders/src/dataloaders/index.js
import DataLoader from 'dataloader';

export const createOrderLoaders = () => ({
  orderById: new DataLoader(async (ids) => {
    const orders = await OrderService.findByIds(ids);
    return ids.map(id => orders.find(o => o.id === id));
  }),
  
  ordersByCustomer: new DataLoader(async (customerIds) => {
    const orderGroups = await OrderService.findByCustomerIds(customerIds);
    return customerIds.map(id => orderGroups[id] || []);
  }, { cache: false }),
  
  orderItemsByOrder: new DataLoader(async (orderIds) => {
    const itemGroups = await OrderItemService.findByOrderIds(orderIds);
    return orderIds.map(id => itemGroups[id] || []);
  }, { cache: false }),
  
  refundsByOrder: new DataLoader(async (orderIds) => {
    const refundGroups = await RefundService.findByOrderIds(orderIds);
    return orderIds.map(id => refundGroups[id] || []);
  }, { cache: false }),
  
  orderEventsByOrder: new DataLoader(async (orderIds) => {
    const eventGroups = await OrderEventService.findByOrderIds(orderIds);
    return orderIds.map(id => eventGroups[id] || []);
  }, { cache: false }),
  
  shippingMethodById: new DataLoader(async (ids) => {
    const methods = await ShippingMethodService.findByIds(ids);
    return ids.map(id => methods.find(m => m.id === id));
  })
});
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

enum Role {
  ADMIN
  USER
  GUEST
}

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
    limit: Int = 20
    offset: Int = 0
  ): PaymentConnection! @authenticated
  
  # Admin queries
  allPayments(
    filter: AdminPaymentFilter
    sort: PaymentSort = { field: CREATED_AT, direction: DESC }
    limit: Int = 50
    offset: Int = 0
  ): PaymentConnection! @auth(requires: ADMIN)
  
  paymentMethods: [PaymentMethod!]! @authenticated
  paymentAnalytics(timeframe: AnalyticsTimeframe!): PaymentAnalytics! @auth(requires: ADMIN)
  fraudAlerts(limit: Int = 20): [FraudAlert!]! @auth(requires: ADMIN)
}

type Mutation {
  createPaymentIntent(input: PaymentIntentInput!): PaymentIntent! @authenticated
  confirmPayment(paymentIntentId: ID!, paymentMethodId: ID!): Payment! @authenticated
  processRefund(paymentId: ID!, amount: Float, reason: String): Refund! @auth(requires: ADMIN)
  captureAuthorization(paymentId: ID!, amount: Float): Payment! @auth(requires: ADMIN)
  voidAuthorization(paymentId: ID!): Payment! @auth(requires: ADMIN)
  
  # Payment methods management
  savePaymentMethod(input: PaymentMethodInput!): SavedPaymentMethod! @authenticated
  removePaymentMethod(id: ID!): Boolean! @authenticated
  updatePaymentMethod(id: ID!, input: PaymentMethodUpdateInput!): SavedPaymentMethod! @authenticated
  
  # Fraud management
  markFraudulent(paymentId: ID!, reason: String!): Payment! @auth(requires: ADMIN)
  approveFraudAlert(alertId: ID!): FraudAlert! @auth(requires: ADMIN)
}

type Payment @key(fields: "id") @auth(requires: USER) {
  id: ID!
  order: Order! @requires(fields: "id orderNumber totalAmount")
  amount: Money!
  currency: String!
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
  currency: String!
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
  last4: String!
  brand: String
  expiryMonth: Int
  expiryYear: Int
  billingAddress: Address
  isDefault: Boolean!
  createdAt: DateTime!
}

type PaymentMethod {
  id: ID!
  name: String!
  type: PaymentMethodType!
  enabled: Boolean!
  supportedCurrencies: [String!]!
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
  supportedCurrencies: [String!]!
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
  score: Float!
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
  percentage: Float!
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
  successRate: Float!
  fraudRate: Float!
  averageAmount: Money!
  methodBreakdown: [PaymentMethodStats!]!
  dailyVolume: [DailyVolumeData!]!
  topDeclineReasons: [DeclineReasonData!]!
}

type PaymentMethodStats {
  method: PaymentMethodType!
  volume: Money!
  count: Int!
  successRate: Float!
}

type DailyVolumeData {
  date: Date!
  volume: Money!
  count: Int!
  successRate: Float!
}

type DeclineReasonData {
  reason: String!
  count: Int!
  percentage: Float!
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
  LOW
  MEDIUM
  HIGH
  CRITICAL
}

enum FraudAlertStatus {
  PENDING_REVIEW
  APPROVED
  DECLINED
  ESCALATED
}

enum FeeType {
  PROCESSING
  GATEWAY
  CURRENCY_CONVERSION
  FRAUD_PROTECTION
  CHARGEBACK
}

enum AnalyticsTimeframe {
  TODAY
  WEEK
  MONTH
  QUARTER
  YEAR
}

enum PaymentSortField {
  CREATED_AT
  AMOUNT
  STATUS
}

input PaymentFilter {
  status: [PaymentStatus!]
  methods: [PaymentMethodType!]
  dateRange: DateRangeInput
  amountRange: PriceRangeInput
  orderId: ID
}

input AdminPaymentFilter {
  status: [PaymentStatus!]
  methods: [PaymentMethodType!]
  gateways: [String!]
  riskLevels: [RiskLevel!]
  dateRange: DateRangeInput
  amountRange: PriceRangeInput
  customerId: ID
  orderId: ID
  fraudulent: Boolean
}

input PaymentSort {
  field: PaymentSortField!
  direction: SortDirection!
}

input PaymentIntentInput {
  orderId: ID!
  amount: Float!
  currency: String!
  paymentMethods: [PaymentMethodType!]
  description: String
  metadata: JSON
}

input PaymentMethodInput {
  type: PaymentMethodType!
  token: String!
  billingAddress: AddressInput!
  isDefault: Boolean = false
}

input PaymentMethodUpdateInput {
  billingAddress: AddressInput
  isDefault: Boolean
}

input DateRangeInput {
  from: DateTime!
  to: DateTime!
}

input PriceRangeInput {
  min: Float
  max: Float
}

input AddressInput {
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

### DataLoader Implementation
```javascript
// payments/src/dataloaders/index.js
import DataLoader from 'dataloader';

export const createPaymentLoaders = () => ({
  paymentById: new DataLoader(async (ids) => {
    const payments = await PaymentService.findByIds(ids);
    return ids.map(id => payments.find(p => p.id === id));
  }),
  
  paymentsByOrder: new DataLoader(async (orderIds) => {
    const paymentGroups = await PaymentService.findByOrderIds(orderIds);
    return orderIds.map(id => paymentGroups[id] || []);
  }, { cache: false }),
  
  paymentsByCustomer: new DataLoader(async (customerIds) => {
    const paymentGroups = await PaymentService.findByCustomerIds(customerIds);
    return customerIds.map(id => paymentGroups[id] || []);
  }, { cache: false }),
  
  refundsByPayment: new DataLoader(async (paymentIds) => {
    const refundGroups = await PaymentRefundService.findByPaymentIds(paymentIds);
    return paymentIds.map(id => refundGroups[id] || []);
  }, { cache: false }),
  
  eventsByPayment: new DataLoader(async (paymentIds) => {
    const eventGroups = await PaymentEventService.findByPaymentIds(paymentIds);
    return paymentIds.map(id => eventGroups[id] || []);
  }, { cache: false }),
  
  savedPaymentMethods: new DataLoader(async (customerIds) => {
    const methodGroups = await SavedPaymentMethodService.findByCustomerIds(customerIds);
    return customerIds.map(id => methodGroups[id] || []);
  }, { cache: false }),
  
  gatewayById: new DataLoader(async (ids) => {
    const gateways = await PaymentGatewayService.findByIds(ids);
    return ids.map(id => gateways.find(g => g.id === id));
  }),
  
  fraudAlertsByPayment: new DataLoader(async (paymentIds) => {
    const alertGroups = await FraudAlertService.findByPaymentIds(paymentIds);
    return paymentIds.map(id => alertGroups[id] || []);
  }, { cache: false })
});
```

## Entity Resolution Strategy

### Primary Keys and References

The Apollo Federation specification indicates that an Object or Interface type can be made into an entity by adding the @key directive to its definition in a subgraph schema. After defining an entity in a schema, other subgraphs can reference that entity in their schemas
.

Key entity relationships:
- **User**: Primary key `id`, owned by Users subgraph
- **Product**: Composite keys `id` and `sku`, owned by Products subgraph  
- **Order**: Primary key `id`, owned by Orders subgraph
- **Payment**: Primary key `id`, owned by Payments subgraph

### Cross-Service References
```graphql
# Orders service references Products
type OrderItem {
  product: Product! @requires(fields: "id sku name price")
  # ... other fields
}

# Payments service references Orders and Users
type Payment {
  order: Order! @requires(fields: "id orderNumber totalAmount")
  # ... other fields
}
```

## Authentication & Authorization

### Directive Implementation

Check out this example of an authorization directive: directive @auth(requires: Role = ADMIN) on OBJECT | FIELD_DEFINITION
 and 
Directive that is used to indicate that the target element is accessible only to the authenticated supergraph users
.

The schema implements multiple auth patterns:
- `@authenticated` - Requires valid authentication
- `@auth(requires: ROLE)` - Role-based access control
- Field-level authorization for sensitive data
- 
Gateway-level Authentication: All incoming requests are authenticated at the gateway, typically by integrating with identity providers (IdPs). The gateway then passes user context to downstream subgraphs


### Context Propagation
```javascript
// Gateway authentication middleware
const context = ({ req }) => {
  const token = req.headers.authorization?.replace('Bearer ', '');
  const user = validateAndDecodeToken(token);
  
  return {
    user,
    dataloaders: {
      users: createUserLoaders(),
      products: createProductLoaders(),
      orders: createOrderLoaders(),
      payments: createPaymentLoaders()
    }
  };
};
```

## N+1 Prevention Strategy

### DataLoader Pattern Implementation

The solution for the N+1 problem—whether for federated or monolithic graphs—is the DataLoader pattern
 and 
The DataLoader pattern is a common solution to solve the N+1 Problem in GraphQL. It's based on the idea of batching requests within lists to reduce the number of requests
.

Key optimization techniques:

1. **Batch Loading**: 
Deduplication: Connectors and DataLoaders ensure that the same request is not sent multiple times


2. **Entity Resolution Batching**:
```javascript
// Router automatically batches entity resolution calls
const resolveProductReferences = async (representations) => {
  const ids = representations.map(rep => rep.id);
  return context.dataloaders.products.loadMany(ids);
};
```

3. **Service-Level Optimization**:
```javascript
// Efficient database queries with IN clauses
const findByIds = async (ids) => {
  return db.query(
    'SELECT * FROM products WHERE id = ANY($1)',
    [ids]
  );
};
```

### Performance Monitoring
```javascript
// DataLoader metrics collection
const createInstrumentedLoader = (batchFn, name) => {
  return new DataLoader(async (keys) => {
    const start = Date.now();
    const result = await batchFn(keys);
    
    metrics.histogram(`dataloader.${name}.batch_size`, keys.length);
    metrics.histogram(`dataloader.${name}.duration`, Date.now() - start);
    
    return result;
  });
};
```

## Query Examples

### Complex Cross-Service Query
```graphql
query GetOrderDetails($orderId: ID!) {
  order(id: $orderId) {
    id
    orderNumber
    status
    totalAmount {
      amount
      currency
      formatted
    }
    customer {
      id
      username
      email
      profile {
        avatar
      }
    }
    items {
      id
      quantity
      unitPrice {
        amount
        currency
      }
      product {
        id
        name
        images {
          url
          altText
        }
        category {
          name
        }
      }
    }
    payment {
      id
      status
      method {
        name
        type
      }
      billingAddress {
        address1
        city
        country
      }
    }
    shippingAddress {
      address1
      city
      country
    }
  }
}
```

This query efficiently:
1. Fetches order from Orders service
2. Resolves customer via Users service DataLoader
3. Resolves products via Products service DataLoader  
4. Resolves payment via Payments service DataLoader
5. All with proper batching and authorization

### Analytics Query with Aggregations
```graphql
query ECommerceAnalytics($timeframe: AnalyticsTimeframe!) {
  orderAnalytics(timeframe: $timeframe) {
    totalOrders
    totalRevenue {
      amount
      formatted
    }
    averageOrderValue {
      amount
      formatted
    }
    topProducts {
      product {
        name
        sku
      }
      quantity
      revenue {
        amount
        formatted
      }
    }
  }
  
  paymentAnalytics(timeframe: $timeframe) {
    totalVolume {
      amount
      formatted  
    }
    successRate
    fraudRate
    methodBreakdown {
      method
      volume {
        amount
        formatted
      }
      successRate
    }
  }
}
```

## Schema Composition and Deployment

### Gateway Configuration
```yaml
# router.yaml
supergraph:
  path: ./supergraph.graphql

authentication:
  providers:
    jwt:
      keys:
        - url: "https://auth.example.com/.well-known/jwks.json"
      header_name: "Authorization"
      header_value_prefix: "Bearer "

authorization:
  directives:
    authenticated: true
    requiresAuth: true

telemetry:
  metrics:
    prometheus:
      enabled: true
  
  tracing:
    jaeger:
      endpoint: "http://jaeger:14268/api/traces"

subgraphs:
  users:
    routing_url: "http://users-service:4001/graphql"
    schema:
      path: "./users.graphql"
  
  products:
    routing_url: "http://products-service:4002/graphql"
    schema:
      path: "./products.graphql"
  
  orders:
    routing_url: "http://orders-service:4003/graphql"
    schema:
      path: "./orders.graphql"
  
  payments:
    routing_url: "http://payments-service:4004/graphql"
    schema:
      path: "./payments.graphql"
```

### CI/CD Schema Validation
```yaml
# .github/workflows/schema-check.yml
name: Schema Check
on:
  pull_request:
    paths:
      - 'services/*/schema.graphql'

jobs:
  schema-check:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      
      - name: Install Rover CLI
        run: curl -sSL https://rover.apollo.dev/nix/latest | sh
      
      - name: Schema Composition Check
        run: |
          rover supergraph compose \
            --config supergraph.yaml \
            --output composed.graphql
      
      - name: Breaking Change Detection
        run: |
          rover subgraph check production@current \
            --schema services/${{ matrix.service }}/schema.graphql \
            --name ${{ matrix.service }}
    
    strategy:
      matrix:
        service: [users, products, orders, payments]
```

This federated e-commerce schema provides:

- **Domain Separation**: 
Clear boundaries between different domains in your application

- **
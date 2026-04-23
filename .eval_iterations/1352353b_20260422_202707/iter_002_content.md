## Overview

This is a comprehensive federated GraphQL schema for an e-commerce platform spanning 4 subgraphs: users, products, orders, and payments. The design follows 
domain-driven design principles to define clear ownership boundaries and avoid overlapping responsibilities
, while implementing 
the DataLoader pattern to solve the N+1 problem
 and comprehensive authorization using custom directives.

## Federation Architecture

### Gateway Configuration

```yaml
# gateway.yaml
federation_version: 2
subgraphs:
  users:
    routing_url: http://users-service:4001/graphql
    schema:
      subgraph_url: http://users-service:4001/graphql
  products:
    routing_url: http://products-service:4002/graphql
    schema:
      subgraph_url: http://products-service:4002/graphql
  orders:
    routing_url: http://orders-service:4003/graphql
    schema:
      subgraph_url: http://orders-service:4003/graphql
  payments:
    routing_url: http://payments-service:4004/graphql
    schema:
      subgraph_url: http://payments-service:4004/graphql

auth:
  jwt:
    jwks_url: "https://auth.example.com/.well-known/jwks.json"
    header_name: "Authorization"
    header_value_prefix: "Bearer "

performance:
  query_planning_cache_size: 1000
  introspection_cache_ttl: 300s

# DataLoader batch configuration
dataloader:
  batch_size_limit: 100
  batch_schedule_delay: 10ms
  deduplication_enabled: true
  cache_ttl: 300s

# Federated tracing
tracing:
  enabled: true
  apollo_tracing: true
  correlation_ids: true
  headers:
    - "x-correlation-id"
    - "x-request-id"

# Apollo Studio integration
apollo_studio:
  schema_registry: true
  performance_monitoring: true
  api_key: ${APOLLO_KEY}
  graph_ref: ${APOLLO_GRAPH_REF}

# Observability
logging:
  level: "info"
  structured: true
  correlation_id_enabled: true
  distributed_tracing: true
  format: "json"

# Schema composition validation
composition:
  breaking_change_detection: true
  automated_checks: true
  deployment_coordination: true
```

## Schema Governance & Evolution Strategy

### Evolution Patterns

```yaml
# schema-evolution.yaml
deprecation_strategy:
  overlap_period: "90_days"  # 3 months overlap for safe migrations
  notification_period: "30_days"  # 1 month notice before removal
  
field_migrations:
  overlap_enabled: true
  migration_tracking: true
  rollback_safety: true

governance:
  automated_validation: true
  business_logic_checks: true
  security_policy_validation: true
  breaking_change_prevention: true

deployment:
  coordinated_releases: true
  maximum_disruption_window: "5_minutes"
  rollback_tested: true
  canary_deployment: true
```

### DataLoader Implementation

```typescript
// DataLoader implementations for efficient batching

// User DataLoader
class UserDataLoader {
  private loader: DataLoader<string, User>;
  
  constructor(private userService: UserService) {
    this.loader = new DataLoader(
      async (userIds: string[]) => {
        const users = await this.userService.batchGetUsers(userIds);
        return userIds.map(id => users.find(user => user.id === id) || null);
      },
      {
        maxBatchSize: 100,
        batchScheduleFn: (callback) => setTimeout(callback, 10),
        cache: true,
        cacheKeyFn: (key) => `user:${key}`,
      }
    );
  }
  
  load(userId: string): Promise<User | null> {
    return this.loader.load(userId);
  }
  
  loadMany(userIds: string[]): Promise<(User | Error)[]> {
    return this.loader.loadMany(userIds);
  }
}

// Product DataLoader with variant support
class ProductDataLoader {
  private productLoader: DataLoader<string, Product>;
  private variantLoader: DataLoader<string, ProductVariant>;
  
  constructor(private productService: ProductService) {
    this.productLoader = new DataLoader(
      async (productIds: string[]) => {
        const products = await this.productService.batchGetProducts(productIds);
        return productIds.map(id => products.find(p => p.id === id) || null);
      },
      { maxBatchSize: 100, batchScheduleFn: (cb) => setTimeout(cb, 10) }
    );
    
    this.variantLoader = new DataLoader(
      async (variantIds: string[]) => {
        const variants = await this.productService.batchGetVariants(variantIds);
        return variantIds.map(id => variants.find(v => v.id === id) || null);
      },
      { maxBatchSize: 100, batchScheduleFn: (cb) => setTimeout(cb, 10) }
    );
  }
}

// Review DataLoader with compound keys
class ReviewDataLoader {
  private loader: DataLoader<string, ProductReview[]>;
  
  constructor(private reviewService: ReviewService) {
    this.loader = new DataLoader(
      async (keys: string[]) => {
        // Keys format: "productId:userId" for compound key batching
        const productIds = keys.map(key => key.split(':')[0]);
        const userIds = keys.map(key => key.split(':')[1]);
        
        const reviews = await this.reviewService.batchGetReviews(productIds, userIds);
        return keys.map(key => {
          const [productId, userId] = key.split(':');
          return reviews.filter(r => r.productId === productId && r.userId === userId);
        });
      },
      { 
        maxBatchSize: 50,
        cacheKeyFn: (key) => `reviews:${key}`,
        batchScheduleFn: (cb) => setTimeout(cb, 10)
      }
    );
  }
}

// Cross-subgraph coordination
class FederatedDataLoaderCoordinator {
  private correlationService: CorrelationService;
  
  constructor() {
    this.correlationService = new CorrelationService();
  }
  
  // Coordinate batching across subgraphs with timing strategy
  async coordinateBatching<T>(
    requests: Array<{ subgraph: string; key: string; loader: DataLoader<string, T> }>
  ): Promise<Array<T | Error>> {
    const correlationId = this.correlationService.generateId();
    
    // Group requests by subgraph for optimal batching
    const groupedRequests = this.groupBySubgraph(requests);
    
    // Execute batches with coordinated timing (100ms window)
    const results = await Promise.allSettled(
      Object.entries(groupedRequests).map(async ([subgraph, subgraphRequests]) => {
        return this.executeBatchWithCorrelation(subgraphRequests, correlationId);
      })
    );
    
    return this.flattenResults(results);
  }
  
  private groupBySubgraph<T>(requests: Array<{ subgraph: string; key: string; loader: DataLoader<string, T> }>) {
    return requests.reduce((acc, request) => {
      if (!acc[request.subgraph]) acc[request.subgraph] = [];
      acc[request.subgraph].push(request);
      return acc;
    }, {} as Record<string, typeof requests>);
  }
}
```

### Customer Journey Optimization

```typescript
// Optimized query patterns for customer workflows

class CustomerJourneyOptimizer {
  constructor(
    private userLoader: UserDataLoader,
    private productLoader: ProductDataLoader,
    private cartLoader: CartDataLoader,
    private orderLoader: OrderDataLoader
  ) {}
  
  // Browse to purchase workflow optimization
  async optimizeBrowseToPurchase(userId: string, productIds: string[]) {
    // Parallel data loading for complete customer context
    const [user, products, cart, recentOrders] = await Promise.all([
      this.userLoader.load(userId),
      this.productLoader.loadMany(productIds),
      this.cartLoader.loadByUser(userId),
      this.orderLoader.loadRecentByUser(userId, 5)
    ]);
    
    // Preload related data for anticipated next steps
    const [recommendations, inventory] = await Promise.all([
      this.loadRecommendations(user, products as Product[]),
      this.loadInventoryStatus(productIds)
    ]);
    
    return {
      user,
      products,
      cart,
      recentOrders,
      recommendations,
      inventory,
      optimizationMetrics: this.calculateMetrics(productIds.length)
    };
  }
  
  // Efficient cross-subgraph query patterns
  async loadCompletePurchaseContext(orderId: string) {
    const order = await this.orderLoader.load(orderId);
    if (!order) return null;
    
    // Batch load all related entities
    const [customer, products, paymentMethods] = await Promise.all([
      this.userLoader.load(order.userId),
      this.productLoader.loadMany(order.items.map(item => item.productId)),
      this.loadPaymentMethods(order.userId)
    ]);
    
    return {
      order,
      customer,
      products,
      paymentMethods,
      queryComplexity: this.calculateQueryComplexity(order)
    };
  }
  
  private calculateMetrics(productCount: number) {
    return {
      productsLoaded: productCount,
      batchEfficiency: 1.0, // Perfect batching
      crossSubgraphQueries: 4,
      estimatedResponseTime: productCount * 2 + 50 // ms
    };
  }
}
```

### 1. Users Subgraph

```graphql
# users/schema.graphql
extend schema
  @link(url: "https://specs.apollo.dev/federation/v2.6", import: [
    "@key", "@shareable", "@external", "@requires", "@provides", "@override"
  ])
  @link(url: "https://mycompany.com/auth/v1.0", import: [
    "@authenticated", "@requiresRole", "@requiresScope"
  ])
  @composeDirective(name: "@authenticated")
  @composeDirective(name: "@requiresRole")
  @composeDirective(name: "@requiresScope")

# Authorization directives
directive @authenticated on FIELD_DEFINITION | OBJECT | INTERFACE
directive @requiresRole(roles: [Role!]!) on FIELD_DEFINITION | OBJECT
directive @requiresScope(scopes: [String!]!) on FIELD_DEFINITION

enum Role {
  ADMIN
  CUSTOMER
  VENDOR
  SUPPORT
}

type User @key(fields: "id") {
  id: ID!
  email: String! @authenticated
  username: String!
  firstName: String!
  lastName: String!
  fullName: String!
  phone: String @authenticated
  dateOfBirth: String @authenticated
  isActive: Boolean! @requiresRole(roles: [ADMIN, SUPPORT])
  createdAt: DateTime!
  updatedAt: DateTime!
  
  # Profile information
  profile: UserProfile @authenticated
  
  # Address management - domain-aligned with user service
  addresses: [Address!]! @authenticated
  primaryAddress: Address @authenticated
  
  # Preferences
  preferences: UserPreferences! @authenticated
  
  # Authentication/security info
  lastLoginAt: DateTime @authenticated
  emailVerified: Boolean! @requiresRole(roles: [ADMIN, SUPPORT])
  
  # External fields from other subgraphs
  orders: [Order!]! @external
  cart: Cart @external
  paymentMethods: [PaymentMethod!]! @external
  reviews: [ProductReview!]! @external
}

type UserProfile @key(fields: "userId") {
  userId: ID! @external
  bio: String
  avatar: String
  socialLinks: [SocialLink!]!
  privacySettings: PrivacySettings!
}

type Address @key(fields: "id") @shareable {
  id: ID!
  userId: ID! @external
  type: AddressType!
  street1: String!
  street2: String
  city: String!
  state: String!
  postalCode: String!
  country: String!
  isDefault: Boolean!
}

enum AddressType {
  HOME
  WORK
  BILLING
  SHIPPING
}

type UserPreferences {
  language: String!
  currency: String!
  timezone: String!
  notifications: NotificationPreferences!
  privacy: PrivacySettings!
}

type NotificationPreferences {
  email: Boolean!
  sms: Boolean!
  push: Boolean!
  orderUpdates: Boolean!
  promotions: Boolean!
  newsletter: Boolean!
}

type PrivacySettings {
  profileVisibility: ProfileVisibility!
  showEmail: Boolean!
  showPhone: Boolean!
  dataProcessingConsent: Boolean!
}

enum ProfileVisibility {
  PUBLIC
  PRIVATE
  FRIENDS_ONLY
}

type SocialLink {
  platform: String!
  url: String!
}

scalar DateTime @shareable

type Query {
  # Self-service user queries
  me: User @authenticated
  
  # Admin queries
  user(id: ID!): User @requiresRole(roles: [ADMIN, SUPPORT])
  users(
    first: Int = 20
    after: String
    filter: UserFilter
    sort: UserSort
  ): UsersConnection @requiresRole(roles: [ADMIN, SUPPORT])
  
  searchUsers(query: String!, first: Int = 20): [User!]! @requiresRole(roles: [ADMIN, SUPPORT])
}

input UserFilter {
  isActive: Boolean
  role: Role
  emailVerified: Boolean
  createdAfter: DateTime
  createdBefore: DateTime
}

input UserSort {
  field: UserSortField!
  direction: SortDirection!
}

enum UserSortField {
  CREATED_AT
  UPDATED_AT
  EMAIL
  LAST_LOGIN_AT
}

enum SortDirection {
  ASC
  DESC
}

type UsersConnection {
  edges: [UserEdge!]!
  pageInfo: PageInfo!
  totalCount: Int!
}

type UserEdge {
  node: User!
  cursor: String!
}

type PageInfo {
  hasNextPage: Boolean!
  hasPreviousPage: Boolean!
  startCursor: String
  endCursor: String
}

type Mutation {
  # User management
  updateProfile(input: UpdateProfileInput!): User! @authenticated
  updatePreferences(input: UpdatePreferencesInput!): User! @authenticated
  
  # Address management
  addAddress(input: AddAddressInput!): Address! @authenticated
  updateAddress(id: ID!, input: UpdateAddressInput!): Address! @authenticated
  deleteAddress(id: ID!): Boolean! @authenticated
  setDefaultAddress(id: ID!): User! @authenticated
  
  # Admin mutations
  activateUser(id: ID!): User! @requiresRole(roles: [ADMIN])
  deactivateUser(id: ID!): User! @requiresRole(roles: [ADMIN])
}

input UpdateProfileInput {
  firstName: String
  lastName: String
  phone: String
  bio: String
  avatar: String
}

input UpdatePreferencesInput {
  language: String
  currency: String
  timezone: String
  notifications: NotificationPreferencesInput
}

input NotificationPreferencesInput {
  email: Boolean
  sms: Boolean
  push: Boolean
  orderUpdates: Boolean
  promotions: Boolean
  newsletter: Boolean
}

input AddAddressInput {
  type: AddressType!
  street1: String!
  street2: String
  city: String!
  state: String!
  postalCode: String!
  country: String!
  isDefault: Boolean = false
}

input UpdateAddressInput {
  type: AddressType
  street1: String
  street2: String
  city: String
  state: String
  postalCode: String
  country: String
  isDefault: Boolean
}
```

### 2. Products Subgraph

```graphql
# products/schema.graphql
extend schema
  @link(url: "https://specs.apollo.dev/federation/v2.6", import: [
    "@key", "@shareable", "@external", "@requires", "@provides", "@override"
  ])
  @link(url: "https://mycompany.com/auth/v1.0", import: [
    "@authenticated", "@requiresRole", "@requiresScope"
  ])
  @composeDirective(name: "@authenticated")
  @composeDirective(name: "@requiresRole")
  @composeDirective(name: "@requiresScope")

directive @authenticated on FIELD_DEFINITION | OBJECT | INTERFACE
directive @requiresRole(roles: [Role!]!) on FIELD_DEFINITION | OBJECT
directive @requiresScope(scopes: [String!]!) on FIELD_DEFINITION

enum Role {
  ADMIN
  CUSTOMER
  VENDOR
  SUPPORT
}

# Extend User entity for product-related fields
extend type User @key(fields: "id") {
  id: ID! @external
  reviews: [ProductReview!]! @requires(fields: "id")
  wishlist: [Product!]! @authenticated @requires(fields: "id")
  viewingHistory: [Product!]! @authenticated @requires(fields: "id")
}

type Product @key(fields: "id") @key(fields: "sku") {
  id: ID!
  sku: String!
  name: String!
  description: String!
  shortDescription: String
  
  # Pricing information
  price: Money!
  compareAtPrice: Money
  costPrice: Money @requiresRole(roles: [ADMIN, VENDOR])
  
  # Inventory
  inventory: ProductInventory!
  
  # Categorization
  category: Category!
  tags: [String!]!
  
  # Media
  images: [ProductImage!]!
  videos: [ProductVideo!]!
  
  # Variants for configurable products
  variants: [ProductVariant!]!
  hasVariants: Boolean!
  
  # Product specifications
  attributes: [ProductAttribute!]!
  specifications: [Specification!]!
  
  # SEO and metadata
  slug: String!
  metaTitle: String
  metaDescription: String
  
  # Status and visibility
  status: ProductStatus!
  isPublished: Boolean!
  publishedAt: DateTime
  
  # Vendor information
  vendor: Vendor!
  
  # Reviews and ratings
  reviews: [ProductReview!]!
  averageRating: Float!
  reviewCount: Int!
  
  # Related products
  relatedProducts: [Product!]!
  upsellProducts: [Product!]!
  crossSellProducts: [Product!]!
  
  # Timestamps
  createdAt: DateTime!
  updatedAt: DateTime!
  
  # External references
  orderItems: [OrderItem!]! @external
  cartItems: [CartItem!]! @external
}

type ProductVariant @key(fields: "id") @key(fields: "sku") {
  id: ID!
  sku: String!
  productId: ID!
  
  # Variant-specific details
  name: String!
  price: Money!
  compareAtPrice: Money
  costPrice: Money @requiresRole(roles: [ADMIN, VENDOR])
  
  # Variant attributes (size, color, etc.)
  attributes: [VariantAttribute!]!
  
  # Inventory for this variant
  inventory: ProductInventory!
  
  # Media
  images: [ProductImage!]!
  
  # Status
  status: ProductStatus!
  isDefault: Boolean!
  
  # Parent product reference
  product: Product!
}

type ProductInventory {
  quantity: Int!
  reserved: Int! @requiresRole(roles: [ADMIN, VENDOR])
  available: Int!
  threshold: Int! @requiresRole(roles: [ADMIN, VENDOR])
  allowBackorder: Boolean!
  trackQuantity: Boolean!
  
  # Warehouse information
  locations: [InventoryLocation!]! @requiresRole(roles: [ADMIN, VENDOR])
}

type InventoryLocation @key(fields: "id") {
  id: ID!
  name: String!
  address: Address! @requires(fields: "id")
  quantity: Int!
  reserved: Int!
  available: Int!
}

# Reference to User's Address
extend type Address @key(fields: "id") {
  id: ID! @external
}

type Category @key(fields: "id") @key(fields: "slug") {
  id: ID!
  name: String!
  slug: String!
  description: String
  parentId: ID
  parent: Category
  children: [Category!]!
  level: Int!
  isActive: Boolean!
  
  # SEO
  metaTitle: String
  metaDescription: String
  
  # Media
  image: String
  banner: String
  
  # Product listing
  products(
    first: Int = 20
    after: String
    filter: ProductFilter
    sort: ProductSort
  ): ProductsConnection!
  
  productCount: Int!
  
  createdAt: DateTime!
  updatedAt: DateTime!
}

type Vendor @key(fields: "id") @key(fields: "slug") {
  id: ID!
  name: String!
  slug: String!
  description: String
  email: String! @requiresRole(roles: [ADMIN, VENDOR])
  phone: String @requiresRole(roles: [ADMIN, VENDOR])
  website: String
  logo: String
  
  # Business information
  businessName: String!
  taxId: String @requiresRole(roles: [ADMIN, VENDOR])
  address: Address! @requires(fields: "id")
  
  # Status
  status: VendorStatus!
  isApproved: Boolean! @requiresRole(roles: [ADMIN])
  
  # Products
  products(
    first: Int = 20
    after: String
    filter: ProductFilter
    sort: ProductSort
  ): ProductsConnection!
  
  productCount: Int!
  
  # Performance metrics
  averageRating: Float!
  reviewCount: Int!
  totalSales: Int! @requiresRole(roles: [ADMIN, VENDOR])
  
  createdAt: DateTime!
  updatedAt: DateTime!
}

enum VendorStatus {
  PENDING
  ACTIVE
  SUSPENDED
  REJECTED
}

type ProductReview @key(fields: "id") @key(fields: "productId userId") {
  id: ID!
  productId: ID!
  userId: ID!
  variantId: ID
  
  # Review content
  title: String!
  content: String!
  rating: Int! # 1-5 stars
  
  # Media
  images: [ReviewImage!]!
  videos: [ReviewVideo!]!
  
  # Verification
  isVerified: Boolean!
  isPurchaseVerified: Boolean!
  
  # Moderation
  status: ReviewStatus!
  moderatedAt: DateTime
  moderatedBy: ID @requiresRole(roles: [ADMIN, SUPPORT])
  
  # References
  product: Product!
  user: User!
  variant: ProductVariant
  
  # Interaction
  helpfulCount: Int!
  isHelpful: Boolean @authenticated
  
  # Timestamps
  createdAt: DateTime!
  updatedAt: DateTime!
}

enum ReviewStatus {
  PENDING
  APPROVED
  REJECTED
  FLAGGED
}

type ProductImage {
  id: ID!
  url: String!
  altText: String
  position: Int!
  isDefault: Boolean!
  variants: [String!]! # responsive variants
}

type ProductVideo {
  id: ID!
  url: String!
  thumbnail: String
  duration: Int
  position: Int!
}

type ReviewImage {
  id: ID!
  url: String!
  altText: String
}

type ReviewVideo {
  id: ID!
  url: String!
  thumbnail: String
  duration: Int
}

type ProductAttribute {
  name: String!
  value: String!
  type: AttributeType!
  isRequired: Boolean!
  isVariant: Boolean! # Used for variant generation
}

type VariantAttribute {
  name: String!
  value: String!
  type: AttributeType!
}

enum AttributeType {
  TEXT
  NUMBER
  BOOLEAN
  COLOR
  SIZE
  MATERIAL
  CUSTOM
}

type Specification {
  name: String!
  value: String!
  group: String
  unit: String
  isHighlight: Boolean!
}

type Money @shareable {
  amount: Float!
  currency: String!
  formatted: String!
}

enum ProductStatus {
  DRAFT
  ACTIVE
  INACTIVE
  ARCHIVED
  OUT_OF_STOCK
}

scalar DateTime @shareable

type Query {
  # Product queries
  product(id: ID, sku: String): Product
  products(
    first: Int = 20
    after: String
    filter: ProductFilter
    sort: ProductSort
  ): ProductsConnection!
  
  searchProducts(
    query: String!
    first: Int = 20
    after: String
    filter: ProductFilter
    sort: ProductSort
  ): ProductsConnection!
  
  # Category queries
  category(id: ID, slug: String): Category
  categories(parentId: ID, level: Int): [Category!]!
  categoryTree: [Category!]!
  
  # Vendor queries
  vendor(id: ID, slug: String): Vendor
  vendors(
    first: Int = 20
    after: String
    filter: VendorFilter
    sort: VendorSort
  ): VendorsConnection!
  
  # Featured/recommended products
  featuredProducts(limit: Int = 10): [Product!]!
  trendingProducts(limit: Int = 10): [Product!]!
  recommendedProducts(userId: ID, limit: Int = 10): [Product!]! @authenticated
  
  # Reviews
  productReviews(
    productId: ID!
    first: Int = 20
    after: String
    sort: ReviewSort
    filter: ReviewFilter
  ): ReviewsConnection!
}

input ProductFilter {
  categoryId: ID
  vendorId: ID
  status: [ProductStatus!]
  isPublished: Boolean
  priceRange: PriceRangeInput
  inStock: Boolean
  hasDiscount: Boolean
  tags: [String!]
  attributes: [AttributeFilterInput!]
}

input PriceRangeInput {
  min: Float
  max: Float
  currency: String = "USD"
}

input AttributeFilterInput {
  name: String!
  values: [String!]!
}

input ProductSort {
  field: ProductSortField!
  direction: SortDirection!
}

enum ProductSortField {
  CREATED_AT
  UPDATED_AT
  NAME
  PRICE
  RATING
  POPULARITY
  SALES_COUNT
}

enum SortDirection {
  ASC
  DESC
}

input VendorFilter {
  status: [VendorStatus!]
  isApproved: Boolean
}

input VendorSort {
  field: VendorSortField!
  direction: SortDirection!
}

enum VendorSortField {
  CREATED_AT
  NAME
  RATING
  PRODUCT_COUNT
}

input ReviewSort {
  field: ReviewSortField!
  direction: SortDirection!
}

enum ReviewSortField {
  CREATED_AT
  RATING
  HELPFUL_COUNT
}

input ReviewFilter {
  rating: [Int!]
  isVerified: Boolean
  status: [ReviewStatus!]
}

type ProductsConnection {
  edges: [ProductEdge!]!
  pageInfo: PageInfo!
  totalCount: Int!
  facets: [ProductFacet!]!
}

type ProductEdge {
  node: Product!
  cursor: String!
}

type ProductFacet {
  name: String!
  values: [FacetValue!]!
}

type FacetValue {
  value: String!
  count: Int!
  isSelected: Boolean!
}

type VendorsConnection {
  edges: [VendorEdge!]!
  pageInfo: PageInfo!
  totalCount: Int!
}

type VendorEdge {
  node: Vendor!
  cursor: String!
}

type ReviewsConnection {
  edges: [ReviewEdge!]!
  pageInfo: PageInfo!
  totalCount: Int!
  summary: ReviewSummary!
}

type ReviewEdge {
  node: ProductReview!
  cursor: String!
}

type ReviewSummary {
  averageRating: Float!
  totalCount: Int!
  ratingDistribution: [RatingCount!]!
}

type RatingCount {
  rating: Int!
  count: Int!
  percentage: Float!
}

type PageInfo {
  hasNextPage: Boolean!
  hasPreviousPage: Boolean!
  startCursor: String
  endCursor: String
}

type Mutation {
  # Product management (vendor/admin only)
  createProduct(input: CreateProductInput!): Product! @requiresRole(roles: [ADMIN, VENDOR])
  updateProduct(id: ID!, input: UpdateProductInput!): Product! @requiresRole(roles: [ADMIN, VENDOR])
  deleteProduct(id: ID!): Boolean! @requiresRole(roles: [ADMIN])
  publishProduct(id: ID!): Product! @requiresRole(roles: [ADMIN, VENDOR])
  unpublishProduct(id: ID!): Product! @requiresRole(roles: [ADMIN, VENDOR])
  
  # Inventory management
  updateInventory(id: ID!, input: UpdateInventoryInput!): Product! @requiresRole(roles: [ADMIN, VENDOR])
  reserveInventory(items: [ReserveInventoryItem!]!): Boolean! @authenticated
  releaseInventory(items: [ReleaseInventoryItem!]!): Boolean! @authenticated
  
  # Reviews
  createReview(input: CreateReviewInput!): ProductReview! @authenticated
  updateReview(id: ID!, input: UpdateReviewInput!): ProductReview! @authenticated
  deleteReview(id: ID!): Boolean! @authenticated
  markReviewHelpful(id: ID!, helpful: Boolean!): ProductReview! @authenticated
  
  # Review moderation
  moderateReview(id: ID!, status: ReviewStatus!, reason: String): ProductReview! @requiresRole(roles: [ADMIN, SUPPORT])
  
  # User actions
  addToWishlist(productId: ID!): User! @authenticated
  removeFromWishlist(productId: ID!): User! @authenticated
  addToViewingHistory(productId: ID!): User! @authenticated
}

input CreateProductInput {
  name: String!
  description: String!
  shortDescription: String
  sku: String!
  price: MoneyInput!
  compareAtPrice: MoneyInput
  costPrice: MoneyInput
  categoryId: ID!
  vendorId: ID
  tags: [String!]!
  attributes: [ProductAttributeInput!]!
  specifications: [SpecificationInput!]!
  images: [ProductImageInput!]!
  inventory: ProductInventoryInput!
  metaTitle: String
  metaDescription: String
  status: ProductStatus = DRAFT
}

input UpdateProductInput {
  name: String
  description: String
  shortDescription: String
  price: MoneyInput
  compareAtPrice: MoneyInput
  costPrice: MoneyInput
  categoryId: ID
  tags: [String!]
  attributes: [ProductAttributeInput!]
  specifications: [SpecificationInput!]
  status: ProductStatus
  metaTitle: String
  metaDescription: String
}

input MoneyInput {
  amount: Float!
  currency: String!
}

input ProductAttributeInput {
  name: String!
  value: String!
  type: AttributeType!
  isRequired: Boolean = false
  isVariant: Boolean = false
}

input SpecificationInput {
  name: String!
  value: String!
  group: String
  unit: String
  isHighlight: Boolean = false
}

input ProductImageInput {
  url: String!
  altText: String
  position: Int!
  isDefault: Boolean = false
}

input ProductInventoryInput {
  quantity: Int!
  threshold: Int = 0
  allowBackorder: Boolean = false
  trackQuantity: Boolean = true
}

input UpdateInventoryInput {
  quantity: Int
  threshold: Int
  allowBackorder: Boolean
  trackQuantity: Boolean
}

input ReserveInventoryItem {
  productId: ID!
  variantId: ID
  quantity: Int!
}

input ReleaseInventoryItem {
  productId: ID!
  variantId: ID
  quantity: Int!
}

input CreateReviewInput {
  productId: ID!
  variantId: ID
  title: String!
  content: String!
  rating: Int! # 1-5
  images: [String!]
}

input UpdateReviewInput {
  title: String
  content: String
  rating: Int
}
```

### 3. Orders Subgraph

```graphql
# orders/schema.graphql
extend schema
  @link(url: "https://specs.apollo.dev/federation/v2.6", import: [
    "@key", "@shareable", "@external", "@requires", "@provides", "@override"
  ])
  @link(url: "https://mycompany.com/auth/v1.0", import: [
    "@authenticated", "@requiresRole", "@requiresScope"
  ])
  @composeDirective(name: "@authenticated")
  @composeDirective(name: "@requiresRole")
  @composeDirective(name: "@requiresScope")

directive @authenticated on FIELD_DEFINITION | OBJECT | INTERFACE
directive @requiresRole(roles: [Role!]!) on FIELD_DEFINITION | OBJECT
directive @requiresScope(scopes: [String!]!) on FIELD_DEFINITION

enum Role {
  ADMIN
  CUSTOMER
  VENDOR
  SUPPORT
}

# Extend User entity for order-related fields
extend type User @key(fields: "id") {
  id: ID! @external
  orders: [Order!]! @requires(fields: "id")
  cart: Cart @authenticated @requires(fields: "id")
  abandonedCarts: [Cart!]! @authenticated @requires(fields: "id")
}

# Extend Product entity for order-related fields
extend type Product @key(fields: "id") {
  id: ID! @external
  name: String! @external
  price: Money! @external
  orderItems: [OrderItem!]! @requires(fields: "id")
  cartItems: [CartItem!]! @requires(fields: "id")
  salesCount: Int! @requiresRole(roles: [ADMIN, VENDOR])
  salesRevenue: Money! @requiresRole(roles: [ADMIN, VENDOR])
}

extend type ProductVariant @key(fields: "id") {
  id: ID! @external
  sku: String! @external
  name: String! @external
  price: Money! @external
}

type Order @key(fields: "id") @key(fields: "orderNumber") {
  id: ID!
  orderNumber: String!
  userId: ID!
  
  # Order status and lifecycle
  status: OrderStatus!
  fulfillmentStatus: FulfillmentStatus!
  paymentStatus: PaymentStatus! @external
  
  # Financial information
  subtotal: Money!
  taxAmount: Money!
  shippingAmount: Money!
  discountAmount: Money!
  totalAmount: Money!
  
  # Currency for the order
  currency: String!
  
  # Items in the order
  items: [OrderItem!]!
  itemCount: Int!
  
  # Customer information
  customer: User!
  
  # Shipping information
  shippingAddress: ShippingAddress!
  billingAddress: BillingAddress!
  
  # Shipping details
  shippingMethod: ShippingMethod!
  estimatedDelivery: DateTime
  actualDelivery: DateTime
  trackingNumber: String
  carrier: String
  
  # Order metadata
  notes: String
  internalNotes: String @requiresRole(roles: [ADMIN, SUPPORT])
  tags: [String!]!
  
  # Promotions and discounts
  appliedPromotions: [AppliedPromotion!]!
  couponCode: String
  
  # Fulfillment
  fulfillments: [Fulfillment!]!
  
  # Returns and refunds
  returns: [OrderReturn!]!
  refunds: [Refund!]! @external
  
  # Order history and timeline
  timeline: [OrderEvent!]!
  
  # Timestamps
  createdAt: DateTime!
  updatedAt: DateTime!
  confirmedAt: DateTime
  shippedAt: DateTime
  deliveredAt: DateTime
  cancelledAt: DateTime
  
  # Analytics
  source: OrderSource!
  channel: OrderChannel!
  
  # External references
  paymentIntentId: String @external
}

type OrderItem @key(fields: "id") @key(fields: "orderId productId") {
  id: ID!
  orderId: ID!
  productId: ID!
  variantId: ID
  
  # Product information at time of order
  name: String!
  sku: String!
  
  # Quantity and pricing
  quantity: Int!
  unitPrice: Money!
  totalPrice: Money!
  
  # Discounts applied to this item
  discountAmount: Money!
  discountReason: String
  
  # Product details
  product: Product!
  variant: ProductVariant
  
  # Fulfillment tracking
  fulfillmentStatus: ItemFulfillmentStatus!
  fulfillmentId: ID
  fulfillment: Fulfillment
  
  # Returns
  returnQuantity: Int!
  refundedQuantity: Int!
  
  # Item-specific customizations
  customizations: [ItemCustomization!]!
  
  # Timestamps
  createdAt: DateTime!
  updatedAt: DateTime!
}

type Cart @key(fields: "id") @key(fields: "userId") {
  id: ID!
  userId: ID!
  
  # Cart state
  status: CartStatus!
  
  # Items in cart
  items: [CartItem!]!
  itemCount: Int!
  
  # Totals
  subtotal: Money!
  estimatedTax: Money!
  estimatedShipping: Money!
  estimatedTotal: Money!
  
  # Applied promotions
  appliedPromotions: [AppliedPromotion!]!
  couponCode: String
  
  # Shipping information (for estimation)
  shippingAddress: Address @external
  
  # Customer
  customer: User!
  
  # Cart lifecycle
  expiresAt: DateTime
  convertedToOrderId: ID
  
  # Timestamps
  createdAt: DateTime!
  updatedAt: DateTime!
  lastActivityAt: DateTime!
  
  # Analytics
  source: CartSource!
  channel: OrderChannel!
}

type CartItem @key(fields: "id") @key(fields: "cartId productId") {
  id: ID!
  cartId: ID!
  productId: ID!
  variantId: ID
  
  # Quantity and pricing
  quantity: Int!
  unitPrice: Money!
  totalPrice: Money!
  
  # Product information
  product: Product!
  variant: ProductVariant
  
  # Customizations
  customizations: [ItemCustomization!]!
  
  # Item state
  isAvailable: Boolean!
  stockLevel: StockLevel!
  
  # Timestamps
  addedAt: DateTime!
  updatedAt: DateTime!
}

type ItemCustomization {
  name: String!
  value: String!
  price: Money
}

type ShippingAddress @shareable {
  id: ID
  firstName: String!
  lastName: String!
  company: String
  street1: String!
  street2: String
  city: String!
  state: String!
  postalCode: String!
  country: String!
  phone: String
  
  # Delivery instructions
  instructions: String
  isResidential: Boolean!
}

type BillingAddress @shareable {
  id: ID
  firstName: String!
  lastName: String!
  company: String
  street1: String!
  street2: String
  city: String!
  state: String!
  postalCode: String!
  country: String!
  phone: String
}

type ShippingMethod @key(fields: "id") {
  id: ID!
  name: String!
  description: String
  carrier: String!
  service: String!
  price: Money!
  estimatedDays: Int!
  trackingSupported: Boolean!
  isActive: Boolean!
}

type AppliedPromotion {
  id: ID!
  code: String!
  name: String!
  type: PromotionType!
  discountAmount: Money!
  description: String!
  appliedAt: DateTime!
}

type Fulfillment @key(fields: "id") {
  id: ID!
  orderId: ID!
  
  # Fulfillment details
  status: FulfillmentStatus!
  method: FulfillmentMethod!
  
  # Items being fulfilled
  items: [FulfillmentItem!]!
  
  # Shipping information
  trackingNumber: String
  carrier: String
  service: String
  
  # Addresses
  origin: FulfillmentLocation!
  destination: ShippingAddress!
  
  # Timeline
  estimatedDelivery: DateTime
  actualPickup: DateTime
  actualDelivery: DateTime
  
  # Notifications
  notificationsSent: [FulfillmentNotification!]!
  
  # Timestamps
  createdAt: DateTime!
  updatedAt: DateTime!
  shippedAt: DateTime
  deliveredAt: DateTime
}

type FulfillmentItem {
  orderItemId: ID!
  quantity: Int!
  orderItem: OrderItem!
}

type FulfillmentLocation {
  name: String!
  address: Address! @external
  contact: String
  phone: String
}

type FulfillmentNotification {
  type: NotificationType!
  sentAt: DateTime!
  channel: NotificationChannel!
  recipient: String!
}

type OrderReturn @key(fields: "id") {
  id: ID!
  orderId: ID!
  returnNumber: String!
  
  # Return details
  status: ReturnStatus!
  reason: ReturnReason!
  customerComments: String
  internalNotes: String @requiresRole(roles: [ADMIN, SUPPORT])
  
  # Items being returned
  items: [ReturnItem!]!
  
  # Financial information
  refundAmount: Money!
  restockingFee: Money!
  returnShippingCost: Money!
  
  # Return shipping
  returnLabel: ReturnLabel
  trackingNumber: String
  
  # Processing
  processedBy: String @requiresRole(roles: [ADMIN, SUPPORT])
  processedAt: DateTime
  
  # References
  order: Order!
  
  # Timestamps
  requestedAt: DateTime!
  approvedAt: DateTime
  receivedAt: DateTime
  completedAt: DateTime
}

type ReturnItem {
  orderItemId: ID!
  quantity: Int!
  reason: ReturnReason!
  condition: ItemCondition!
  orderItem: OrderItem!
}

type ReturnLabel {
  url: String!
  trackingNumber: String!
  carrier: String!
  cost: Money!
}

type OrderEvent @key(fields: "id") {
  id: ID!
  orderId: ID!
  type: OrderEventType!
  description: String!
  actor: String # User ID or system
  metadata: JSON
  createdAt: DateTime!
}

# External types from other subgraphs
extend type Address @key(fields: "id") {
  id: ID! @external
}

type Money @shareable {
  amount: Float!
  currency: String!
  formatted: String!
}

# Enums
enum OrderStatus {
  PENDING
  CONFIRMED
  PROCESSING
  SHIPPED
  DELIVERED
  CANCELLED
  RETURNED
  REFUNDED
}

enum FulfillmentStatus {
  PENDING
  PROCESSING
  SHIPPED
  IN_TRANSIT
  DELIVERED
  FAILED
  CANCELLED
}

enum PaymentStatus {
  PENDING
  AUTHORIZED
  PAID
  FAILED
  CANCELLED
  REFUNDED
  PARTIALLY_REFUNDED
}

enum ItemFulfillmentStatus {
  PENDING
  ALLOCATED
  PICKED
  PACKED
  SHIPPED
  DELIVERED
  CANCELLED
}

enum CartStatus {
  ACTIVE
  ABANDONED
  CONVERTED
  EXPIRED
}

enum StockLevel {
  IN_STOCK
  LOW_STOCK
  OUT_OF_STOCK
  DISCONTINUED
}

enum PromotionType {
  PERCENTAGE_DISCOUNT
  FIXED_AMOUNT_DISCOUNT
  FREE_SHIPPING
  BUY_X_GET_Y
  TIERED_DISCOUNT
}

enum FulfillmentMethod {
  STANDARD_SHIPPING
  EXPRESS_SHIPPING
  OVERNIGHT_SHIPPING
  PICKUP
  DIGITAL_DELIVERY
}

enum ReturnStatus {
  REQUESTED
  APPROVED
  REJECTED
  IN_TRANSIT
  RECEIVED
  PROCESSING
  COMPLETED
  CANCELLED
}

enum ReturnReason {
  DEFECTIVE
  WRONG_ITEM
  NOT_AS_DESCRIBED
  SIZE_ISSUE
  CHANGED_MIND
  DAMAGED_IN_TRANSIT
  LATE_DELIVERY
  OTHER
}

enum ItemCondition {
  NEW
  LIKE_NEW
  GOOD
  FAIR
  POOR
  DAMAGED
}

enum OrderEventType {
  CREATED
  CONFIRMED
  PAYMENT_RECEIVED
  PROCESSING_STARTED
  SHIPPED
  DELIVERED
  CANCELLED
  RETURNED
  REFUNDED
  UPDATED
  NOTE_ADDED
}

enum OrderSource {
  WEB
  MOBILE_APP
  ADMIN
  API
  IMPORT
}

enum OrderChannel {
  ONLINE
  PHONE
  EMAIL
  SOCIAL_MEDIA
  MARKETPLACE
}

enum
```hcl
# ============================================================================
# Root Configuration - main.tf
# ============================================================================

terraform {
  required_version = ">= 1.6"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
  
  backend "s3" {
    bucket         = "my-terraform-state-bucket" # Replace with your bucket
    key            = "${terraform.workspace}/terraform.tfstate"
    region         = "us-east-1"
    dynamodb_table = "terraform-state-locks"
    encrypt        = true
  }
}

provider "aws" {
  region = var.aws_region
  
  default_tags {
    tags = {
      Environment   = terraform.workspace
      Project       = var.project_name
      ManagedBy     = "Terraform"
      WorkspaceName = terraform.workspace
    }
  }
}

locals {
  environment_config = var.environment_configs[terraform.workspace]
  
  common_tags = {
    Environment = terraform.workspace
    Project     = var.project_name
    ManagedBy   = "Terraform"
  }
}

# ============================================================================
# Data Sources
# ============================================================================

data "aws_availability_zones" "available" {
  state = "available"
}

data "aws_caller_identity" "current" {}

data "aws_ec2_managed_prefix_list" "cloudfront" {
  name = "com.amazonaws.global.cloudfront.origin-facing"
}

# ============================================================================
# VPC Module
# ============================================================================

module "vpc" {
  source = "./modules/vpc"
  
  environment    = terraform.workspace
  project_name   = var.project_name
  vpc_cidr       = local.environment_config.vpc_cidr
  azs           = slice(data.aws_availability_zones.available.names, 0, local.environment_config.az_count)
  
  tags = local.common_tags
}

# ============================================================================
# Security Groups Module
# ============================================================================

module "security_groups" {
  source = "./modules/security-groups"
  
  environment  = terraform.workspace
  project_name = var.project_name
  vpc_id       = module.vpc.vpc_id
  cloudfront_prefix_list_id = data.aws_ec2_managed_prefix_list.cloudfront.id
  
  tags = local.common_tags
}

# ============================================================================
# CloudFront Module
# ============================================================================

module "cloudfront" {
  source = "./modules/cloudfront"
  
  environment     = terraform.workspace
  project_name    = var.project_name
  alb_dns_name    = module.alb.dns_name
  
  tags = local.common_tags
}

# ============================================================================
# ALB Module
# ============================================================================

module "alb" {
  source = "./modules/alb"
  
  environment         = terraform.workspace
  project_name        = var.project_name
  vpc_id              = module.vpc.vpc_id
  public_subnet_ids   = module.vpc.public_subnet_ids
  alb_security_groups = [module.security_groups.alb_security_group_id]
  
  enable_deletion_protection = local.environment_config.enable_deletion_protection
  cloudfront_origin_header_value = module.cloudfront.origin_header_value
  
  tags = local.common_tags
}

# ============================================================================
# RDS Module
# ============================================================================

module "rds" {
  source = "./modules/rds"
  
  environment           = terraform.workspace
  project_name          = var.project_name
  vpc_id                = module.vpc.vpc_id
  private_subnet_ids    = module.vpc.private_subnet_ids
  database_security_groups = [module.security_groups.rds_security_group_id]
  
  instance_class        = local.environment_config.rds_instance_class
  allocated_storage     = local.environment_config.rds_allocated_storage
  multi_az              = local.environment_config.rds_multi_az
  backup_retention_days = local.environment_config.rds_backup_retention
  
  tags = local.common_tags
}

# ============================================================================
# IAM Module
# ============================================================================

module "iam" {
  source = "./modules/iam"
  
  environment  = terraform.workspace
  project_name = var.project_name
  
  tags = local.common_tags
}

# ============================================================================
# ECS Module
# ============================================================================

module "ecs" {
  source = "./modules/ecs"
  
  environment              = terraform.workspace
  project_name             = var.project_name
  vpc_id                   = module.vpc.vpc_id
  private_subnet_ids       = module.vpc.private_subnet_ids
  ecs_security_groups      = [module.security_groups.ecs_security_group_id]
  
  target_group_arn         = module.alb.target_group_arn
  execution_role_arn       = module.iam.ecs_execution_role_arn
  web_task_role_arn        = module.iam.ecs_web_task_role_arn
  api_task_role_arn        = module.iam.ecs_api_task_role_arn
  
  desired_count           = local.environment_config.ecs_desired_count
  cpu                     = local.environment_config.ecs_cpu
  memory                  = local.environment_config.ecs_memory
  
  database_secret_arn = module.rds.secret_arn
  
  tags = local.common_tags
}

# ============================================================================
# Variables - variables.tf
# ============================================================================

variable "aws_region" {
  description = "AWS region for resources"
  type        = string
  default     = "us-east-1"
  
  validation {
    condition     = can(regex("^[a-z0-9-]+$", var.aws_region))
    error_message = "AWS region must contain only lowercase letters, numbers, and hyphens."
  }
}

variable "project_name" {
  description = "Name of the project"
  type        = string
  default     = "myapp"
  
  validation {
    condition     = can(regex("^[a-z0-9-]+$", var.project_name))
    error_message = "Project name must contain only lowercase letters, numbers, and hyphens."
  }
}

variable "environment_configs" {
  description = "Environment-specific configurations"
  type = map(object({
    vpc_cidr                   = string
    az_count                   = number
    ecs_desired_count          = number
    ecs_cpu                    = number
    ecs_memory                 = number
    rds_instance_class         = string
    rds_allocated_storage      = number
    rds_multi_az               = bool
    rds_backup_retention       = number
    enable_deletion_protection = bool
  }))
  
  validation {
    condition = alltrue([
      for k, v in var.environment_configs : contains(["dev", "staging", "prod"], k)
    ])
    error_message = "Environment keys must be one of: dev, staging, prod."
  }
  
  default = {
    dev = {
      vpc_cidr                   = "10.0.0.0/16"
      az_count                   = 2
      ecs_desired_count          = 1
      ecs_cpu                    = 256
      ecs_memory                 = 512
      rds_instance_class         = "db.t3.micro"
      rds_allocated_storage      = 20
      rds_multi_az               = false
      rds_backup_retention       = 1
      enable_deletion_protection = false
    }
    staging = {
      vpc_cidr                   = "10.1.0.0/16"
      az_count                   = 2
      ecs_desired_count          = 2
      ecs_cpu                    = 512
      ecs_memory                 = 1024
      rds_instance_class         = "db.t3.small"
      rds_allocated_storage      = 50
      rds_multi_az               = false
      rds_backup_retention       = 3
      enable_deletion_protection = false
    }
    prod = {
      vpc_cidr                   = "10.2.0.0/16"
      az_count                   = 3
      ecs_desired_count          = 3
      ecs_cpu                    = 1024
      ecs_memory                 = 2048
      rds_instance_class         = "db.r6g.large"
      rds_allocated_storage      = 100
      rds_multi_az               = true
      rds_backup_retention       = 7
      enable_deletion_protection = true
    }
  }
}

# ============================================================================
# Outputs - outputs.tf
# ============================================================================

output "vpc_id" {
  description = "ID of the VPC"
  value       = module.vpc.vpc_id
}

output "vpc_info" {
  description = "VPC information for module composition"
  value = {
    id   = module.vpc.vpc_id
    cidr = module.vpc.vpc_cidr
  }
}

output "alb_dns_name" {
  description = "DNS name of the ALB"
  value       = module.alb.dns_name
}

output "alb_zone_id" {
  description = "Zone ID of the ALB"
  value       = module.alb.zone_id
}

output "cloudfront_distribution_domain_name" {
  description = "CloudFront distribution domain name"
  value       = module.cloudfront.distribution_domain_name
}

output "rds_endpoint" {
  description = "RDS endpoint"
  value       = module.rds.endpoint
  sensitive   = true
}

output "ecs_cluster_name" {
  description = "Name of the ECS cluster"
  value       = module.ecs.cluster_name
}

output "ecs_service_name" {
  description = "Name of the ECS service"
  value       = module.ecs.service_name
}

# ============================================================================
# VPC Module - modules/vpc/main.tf
# ============================================================================

terraform {
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
}

locals {
  private_subnets = [for i, az in var.azs : cidrsubnet(var.vpc_cidr, 4, i)]
  public_subnets  = [for i, az in var.azs : cidrsubnet(var.vpc_cidr, 4, i + length(var.azs))]
  database_subnets = [for i, az in var.azs : cidrsubnet(var.vpc_cidr, 4, i + (length(var.azs) * 2))]
}

resource "aws_vpc" "main" {
  cidr_block           = var.vpc_cidr
  enable_dns_hostnames = true
  enable_dns_support   = true
  
  tags = merge(var.tags, {
    Name = "${var.project_name}-${var.environment}-vpc"
  })
}

# VPC Flow Logs
resource "aws_flow_log" "vpc" {
  iam_role_arn         = aws_iam_role.flow_log.arn
  log_destination      = aws_cloudwatch_log_group.vpc_flow_logs.arn
  traffic_type         = "ALL"
  vpc_id               = aws_vpc.main.id
  log_destination_type = "cloud-watch-logs"
  
  tags = merge(var.tags, {
    Name = "${var.project_name}-${var.environment}-vpc-flow-logs"
  })
}

resource "aws_cloudwatch_log_group" "vpc_flow_logs" {
  name              = "/aws/vpc/flowlogs/${var.project_name}-${var.environment}"
  retention_in_days = var.environment == "prod" ? 365 : 30
  kms_key_id        = aws_kms_key.logs.arn
  
  tags = var.tags
}

resource "aws_iam_role" "flow_log" {
  name = "${var.project_name}-${var.environment}-flow-log-role"
  
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Action = "sts:AssumeRole"
        Effect = "Allow"
        Principal = {
          Service = "vpc-flow-logs.amazonaws.com"
        }
      }
    ]
  })
  
  tags = var.tags
}

data "aws_iam_policy_document" "flow_log" {
  statement {
    effect = "Allow"
    actions = [
      "logs:CreateLogGroup",
      "logs:CreateLogStream",
      "logs:PutLogEvents",
      "logs:DescribeLogGroups",
      "logs:DescribeLogStreams"
    ]
    resources = ["${aws_cloudwatch_log_group.vpc_flow_logs.arn}:*"]
  }
}

resource "aws_iam_policy" "flow_log" {
  name   = "${var.project_name}-${var.environment}-flow-log-policy"
  policy = data.aws_iam_policy_document.flow_log.json
  
  tags = var.tags
}

resource "aws_iam_role_policy_attachment" "flow_log" {
  role       = aws_iam_role.flow_log.name
  policy_arn = aws_iam_policy.flow_log.arn
}

# KMS Key for Log Encryption
resource "aws_kms_key" "logs" {
  description             = "KMS key for log encryption"
  deletion_window_in_days = var.environment == "prod" ? 30 : 7
  
  policy = data.aws_iam_policy_document.logs_kms.json
  
  tags = merge(var.tags, {
    Name = "${var.project_name}-${var.environment}-logs-key"
  })
}

resource "aws_kms_alias" "logs" {
  name          = "alias/${var.project_name}-${var.environment}-logs"
  target_key_id = aws_kms_key.logs.key_id
}

data "aws_iam_policy_document" "logs_kms" {
  statement {
    sid       = "Enable IAM User Permissions"
    effect    = "Allow"
    principals {
      type        = "AWS"
      identifiers = ["arn:aws:iam::${data.aws_caller_identity.current.account_id}:root"]
    }
    actions   = ["kms:*"]
    resources = ["*"]
  }
  
  statement {
    sid       = "Allow CloudWatch Logs"
    effect    = "Allow"
    principals {
      type        = "Service"
      identifiers = ["logs.${data.aws_region.current.name}.amazonaws.com"]
    }
    actions = [
      "kms:Encrypt",
      "kms:Decrypt",
      "kms:ReEncrypt*",
      "kms:GenerateDataKey*",
      "kms:DescribeKey"
    ]
    resources = ["*"]
  }
}

resource "aws_subnet" "private" {
  count = length(var.azs)
  
  vpc_id            = aws_vpc.main.id
  cidr_block        = local.private_subnets[count.index]
  availability_zone = var.azs[count.index]
  
  tags = merge(var.tags, {
    Name = "${var.project_name}-${var.environment}-private-${var.azs[count.index]}"
    Type = "Private"
  })
}

resource "aws_subnet" "public" {
  count = length(var.azs)
  
  vpc_id                  = aws_vpc.main.id
  cidr_block              = local.public_subnets[count.index]
  availability_zone       = var.azs[count.index]
  map_public_ip_on_launch = true
  
  tags = merge(var.tags, {
    Name = "${var.project_name}-${var.environment}-public-${var.azs[count.index]}"
    Type = "Public"
  })
}

resource "aws_subnet" "database" {
  count = length(var.azs)
  
  vpc_id            = aws_vpc.main.id
  cidr_block        = local.database_subnets[count.index]
  availability_zone = var.azs[count.index]
  
  tags = merge(var.tags, {
    Name = "${var.project_name}-${var.environment}-database-${var.azs[count.index]}"
    Type = "Database"
  })
}

resource "aws_internet_gateway" "main" {
  vpc_id = aws_vpc.main.id
  
  tags = merge(var.tags, {
    Name = "${var.project_name}-${var.environment}-igw"
  })
}

resource "aws_eip" "nat" {
  count = length(var.azs)
  
  domain = "vpc"
  
  tags = merge(var.tags, {
    Name = "${var.project_name}-${var.environment}-nat-eip-${count.index + 1}"
  })
  
  depends_on = [aws_internet_gateway.main]
}

resource "aws_nat_gateway" "main" {
  count = length(var.azs)
  
  allocation_id = aws_eip.nat[count.index].id
  subnet_id     = aws_subnet.public[count.index].id
  
  tags = merge(var.tags, {
    Name = "${var.project_name}-${var.environment}-nat-${count.index + 1}"
  })
  
  depends_on = [aws_internet_gateway.main]
}

resource "aws_route_table" "public" {
  vpc_id = aws_vpc.main.id
  
  route {
    cidr_block = "0.0.0.0/0"
    gateway_id = aws_internet_gateway.main.id
  }
  
  tags = merge(var.tags, {
    Name = "${var.project_name}-${var.environment}-public-rt"
  })
}

resource "aws_route_table" "private" {
  count = length(var.azs)
  
  vpc_id = aws_vpc.main.id
  
  route {
    cidr_block     = "0.0.0.0/0"
    nat_gateway_id = aws_nat_gateway.main[count.index].id
  }
  
  tags = merge(var.tags, {
    Name = "${var.project_name}-${var.environment}-private-rt-${count.index + 1}"
  })
}

resource "aws_route_table" "database" {
  vpc_id = aws_vpc.main.id
  
  tags = merge(var.tags, {
    Name = "${var.project_name}-${var.environment}-database-rt"
  })
}

resource "aws_route_table_association" "public" {
  count = length(var.azs)
  
  subnet_id      = aws_subnet.public[count.index].id
  route_table_id = aws_route_table.public.id
}

resource "aws_route_table_association" "private" {
  count = length(var.azs)
  
  subnet_id      = aws_subnet.private[count.index].id
  route_table_id = aws_route_table.private[count.index].id
}

resource "aws_route_table_association" "database" {
  count = length(var.azs)
  
  subnet_id      = aws_subnet.database[count.index].id
  route_table_id = aws_route_table.database.id
}

# VPC Endpoints for cost optimization and security
resource "aws_vpc_endpoint" "s3" {
  vpc_id              = aws_vpc.main.id
  service_name        = "com.amazonaws.${data.aws_region.current.name}.s3"
  vpc_endpoint_type   = "Gateway"
  route_table_ids     = concat(aws_route_table.private[*].id, [aws_route_table.database.id])
  
  policy = jsonencode({
    Statement = [
      {
        Effect = "Allow"
        Principal = "*"
        Action = [
          "s3:GetObject",
          "s3:PutObject"
        ]
        Resource = [
          "arn:aws:s3:::${var.project_name}-*/*",
          "arn:aws:s3:::aws-cli/*",
          "arn:aws:s3:::amazon-ssm-${data.aws_region.current.name}/*"
        ]
      }
    ]
  })
  
  tags = merge(var.tags, {
    Name = "${var.project_name}-${var.environment}-s3-endpoint"
  })
}

resource "aws_vpc_endpoint" "ecr_dkr" {
  vpc_id              = aws_vpc.main.id
  service_name        = "com.amazonaws.${data.aws_region.current.name}.ecr.dkr"
  vpc_endpoint_type   = "Interface"
  subnet_ids          = aws_subnet.private[*].id
  security_group_ids  = [aws_security_group.vpc_endpoints.id]
  
  private_dns_enabled = true
  
  policy = jsonencode({
    Statement = [
      {
        Effect = "Allow"
        Principal = "*"
        Action = [
          "ecr:BatchCheckLayerAvailability",
          "ecr:GetDownloadUrlForLayer",
          "ecr:BatchGetImage"
        ]
        Resource = "arn:aws:ecr:${data.aws_region.current.name}:${data.aws_caller_identity.current.account_id}:repository/${var.project_name}-*"
      }
    ]
  })
  
  tags = merge(var.tags, {
    Name = "${var.project_name}-${var.environment}-ecr-dkr-endpoint"
  })
}

resource "aws_vpc_endpoint" "ecr_api" {
  vpc_id              = aws_vpc.main.id
  service_name        = "com.amazonaws.${data.aws_region.current.name}.ecr.api"
  vpc_endpoint_type   = "Interface"
  subnet_ids          = aws_subnet.private[*].id
  security_group_ids  = [aws_security_group.vpc_endpoints.id]
  
  private_dns_enabled = true
  
  policy = jsonencode({
    Statement = [
      {
        Effect = "Allow"
        Principal = "*"
        Action = [
          "ecr:GetAuthorizationToken",
          "ecr:BatchCheckLayerAvailability"
        ]
        Resource = "arn:aws:ecr:${data.aws_region.current.name}:${data.aws_caller_identity.current.account_id}:repository/${var.project_name}-*"
      }
    ]
  })
  
  tags = merge(var.tags, {
    Name = "${var.project_name}-${var.environment}-ecr-api-endpoint"
  })
}

resource "aws_vpc_endpoint" "logs" {
  vpc_id              = aws_vpc.main.id
  service_name        = "com.amazonaws.${data.aws_region.current.name}.logs"
  vpc_endpoint_type   = "Interface"
  subnet_ids          = aws_subnet.private[*].id
  security_group_ids  = [aws_security_group.vpc_endpoints.id]
  
  private_dns_enabled = true
  
  policy = jsonencode({
    Statement = [
      {
        Effect = "Allow"
        Principal = "*"
        Action = [
          "logs:CreateLogGroup",
          "logs:CreateLogStream",
          "logs:PutLogEvents"
        ]
        Resource = "arn:aws:logs:${data.aws_region.current.name}:${data.aws_caller_identity.current.account_id}:log-group:/ecs/${var.project_name}-${var.environment}-*"
      }
    ]
  })
  
  tags = merge(var.tags, {
    Name = "${var.project_name}-${var.environment}-logs-endpoint"
  })
}

resource "aws_vpc_endpoint" "ecs" {
  vpc_id              = aws_vpc.main.id
  service_name        = "com.amazonaws.${data.aws_region.current.name}.ecs"
  vpc_endpoint_type   = "Interface"
  subnet_ids          = aws_subnet.private[*].id
  security_group_ids  = [aws_security_group.vpc_endpoints.id]
  
  private_dns_enabled = true
  
  policy = jsonencode({
    Statement = [
      {
        Effect = "Allow"
        Principal = "*"
        Action = [
          "ecs:CreateCluster",
          "ecs:DescribeClusters",
          "ecs:RegisterTaskDefinition",
          "ecs:RunTask",
          "ecs:StopTask",
          "ecs:DescribeTasks"
        ]
        Resource = [
          "arn:aws:ecs:${data.aws_region.current.name}:${data.aws_caller_identity.current.account_id}:cluster/${var.project_name}-${var.environment}-*",
          "arn:aws:ecs:${data.aws_region.current.name}:${data.aws_caller_identity.current.account_id}:task-definition/${var.project_name}-${var.environment}-*"
        ]
      }
    ]
  })
  
  tags = merge(var.tags, {
    Name = "${var.project_name}-${var.environment}-ecs-endpoint"
  })
}

resource "aws_security_group" "vpc_endpoints" {
  name_prefix = "${var.project_name}-${var.environment}-vpc-endpoints-"
  description = "Security group for VPC endpoints"
  vpc_id      = aws_vpc.main.id
  
  ingress {
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = [var.vpc_cidr]
  }
  
  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
  
  tags = merge(var.tags, {
    Name = "${var.project_name}-${var.environment}-vpc-endpoints-sg"
  })
  
  lifecycle {
    create_before_destroy = true
  }
}

data "aws_region" "current" {}
data "aws_caller_identity" "current" {}

# ============================================================================
# VPC Module Variables - modules/vpc/variables.tf
# ============================================================================

variable "environment" {
  description = "Environment name"
  type        = string
}

variable "project_name" {
  description = "Project name"
  type        = string
}

variable "vpc_cidr" {
  description = "CIDR block for the VPC"
  type        = string
}

variable "azs" {
  description = "List of availability zones"
  type        = list(string)
}

variable "tags" {
  description = "Tags to apply to resources"
  type        = map(string)
  default     = {}
}

# ============================================================================
# VPC Module Outputs - modules/vpc/outputs.tf
# ============================================================================

output "vpc_id" {
  description = "ID of the VPC"
  value       = aws_vpc.main.id
}

output "vpc_cidr" {
  description = "CIDR block of the VPC"
  value       = aws_vpc.main.cidr_block
}

output "private_subnet_ids" {
  description = "IDs of the private subnets"
  value       = aws_subnet.private[*].id
}

output "public_subnet_ids" {
  description = "IDs of the public subnets"
  value       = aws_subnet.public[*].id
}

output "database_subnet_ids" {
  description = "IDs of the database subnets"
  value       = aws_subnet.database[*].id
}

output "internet_gateway_id" {
  description = "ID of the Internet Gateway"
  value       = aws_internet_gateway.main.id
}

output "nat_gateway_ids" {
  description = "IDs of the NAT Gateways"
  value       = aws_nat_gateway.main[*].id
}

# ============================================================================
# Security Groups Module - modules/security-groups/main.tf
# ============================================================================

terraform {
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
}

resource "aws_security_group" "alb" {
  name_prefix = "${var.project_name}-${var.environment}-alb-"
  description = "Security group for Application Load Balancer"
  vpc_id      = var.vpc_id
  
  ingress {
    description     = "HTTP from CloudFront"
    from_port       = 80
    to_port         = 80
    protocol        = "tcp"
    prefix_list_ids = [var.cloudfront_prefix_list_id]
  }
  
  ingress {
    description     = "HTTPS from CloudFront"
    from_port       = 443
    to_port         = 443
    protocol        = "tcp"
    prefix_list_ids = [var.cloudfront_prefix_list_id]
  }
  
  egress {
    description = "All outbound traffic to ECS"
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    security_groups = [aws_security_group.ecs.id]
  }
  
  tags = merge(var.tags, {
    Name = "${var.project_name}-${var.environment}-alb-sg"
  })
  
  lifecycle {
    create_before_destroy = true
  }
}

resource "aws_security_group" "ecs" {
  name_prefix = "${var.project_name}-${var.environment}-ecs-"
  description = "Security group for ECS tasks"
  vpc_id      = var.vpc_id
  
  ingress {
    description     = "HTTP from ALB"
    from_port       = 80
    to_port         = 80
    protocol        = "tcp"
    security_groups = [aws_security_group.alb.id]
  }
  
  ingress {
    description     = "Application port from ALB"
    from_port       = 3000
    to_port         = 3000
    protocol        = "tcp"
    security_groups = [aws_security_group.alb.id]
  }
  
  egress {
    description = "HTTPS for API calls"
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }
  
  egress {
    description     = "Database access"
    from_port       = 5432
    to_port         = 5432
    protocol        = "tcp"
    security_groups = [aws_security_group.rds.id]
  }
  
  tags = merge(var.tags, {
    Name = "${var.project_name}-${var.environment}-ecs-sg"
  })
  
  lifecycle {
    create_before_destroy = true
  }
}

resource "aws_security_group" "rds" {
  name_prefix = "${var.project_name}-${var.environment}-rds-"
  description = "Security group for RDS database"
  vpc_id      = var.vpc_id
  
  ingress {
    description     = "PostgreSQL from ECS"
    from_port       = 5432
    to_port         = 5432
    protocol        = "tcp"
    security_groups = [aws_security_group.ecs.id]
  }
  
  tags = merge(var.tags, {
    Name = "${var.project_name}-${var.environment}-rds-sg"
  })
  
  lifecycle {
    create_before_destroy = true
  }
}

# ============================================================================
# Security Groups Module Variables - modules/security-groups/variables.tf
# ============================================================================

variable "environment" {
  description = "Environment name"
  type        = string
}

variable "project_name" {
  description = "Project name"
  type        = string
}

variable "vpc_id" {
  description = "ID of the VPC"
  type        = string
}

variable "cloudfront_prefix_list_id" {
  description = "CloudFront managed prefix list ID"
  type        = string
}

variable "tags" {
  description = "Tags to apply to resources"
  type        = map(string)
  default     = {}
}

# ============================================================================
# Security Groups Module Outputs - modules/security-groups/outputs.tf
# ============================================================================

output "alb_security_group_id" {
  description = "ID of the ALB security group"
  value       = aws_security_group.alb.id
}

output "ecs_security_group_id" {
  description = "ID of the ECS security group"
  value       = aws_security_group.ecs.id
}

output "rds_security_group_id" {
  description = "ID of the RDS security group"
  value       = aws_security_group.rds.id
}

# ============================================================================
# IAM Module - modules/iam/main.tf
# ============================================================================

terraform {
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
}

data "aws_caller_identity" "current" {}
data "aws_region" "current" {}

# ECS Task Execution Role - for pulling images and logging
resource "aws_iam_role" "ecs_execution_role" {
  name                 = "${var.project_name}-${var.environment}-ecs-execution-role"
  max_session_duration = 3600
  
  assume_role_policy = data.aws_iam_policy_document.ecs_assume_role.json
  
  tags = var.tags
}

data "aws_iam_policy_document" "ecs_assume_role" {
  statement {
    effect = "Allow"
    
    principals {
      type        = "Service"
      identifiers = ["ecs-tasks.amazonaws.com"]
    }
    
    actions = ["sts:AssumeRole"]
    
    condition {
      test     = "StringEquals"
      variable = "aws:RequestedRegion"
      values   = [data.aws_region.current.name]
    }
  }
}

data "aws_iam_policy_document" "ecs_execution" {
  statement {
    effect = "Allow"
    actions = [
      "ecr:GetAuthorizationToken"
    ]
    resources = ["*"]
  }
  
  statement {
    effect = "Allow"
    actions = [
      "ecr:BatchCheckLayerAvailability",
      "ecr:GetDownloadUrlForLayer",
      "ecr:BatchGetImage"
    ]
    resources = ["arn:aws:ecr:${data.aws_region.current.name}:${data.aws_caller_identity.current.account_id}:repository/${var.project_name}-*"]
  }
  
  statement {
    effect = "Allow"
    actions = [
      "logs:CreateLogGroup",
      "logs:CreateLogStream",
      "logs:PutLogEvents",
      "logs:DescribeLogStreams"
    ]
    resources = ["arn:aws:logs:${data.aws_region.current.name}:${data.aws_caller_identity.current.account_id}:log-group:/ecs/${var.project_name}-${var.environment}-*"]
  }
  
  statement {
    effect = "Allow"
    actions = [
      "secretsmanager:GetSecretValue"
    ]
    resources = ["arn:aws:secretsmanager:${data.aws_region.current.name}:${data.aws_caller_identity.current.account_id}:secret:${var.project_name}/${var.environment}/*"]
  }
}

resource "aws_iam_policy" "ecs_execution_policy" {
  name        = "${var.project_name}-${var.environment}-ecs-execution-policy"
  description = "Least privilege policy for ECS task execution"
  
  policy = data.aws_iam_policy_document.ecs_execution.json
  
  tags = var.tags
}

resource "aws_iam_role_policy_attachment" "ecs_execution_policy_attachment" {
  role       = aws_iam_role.ecs_execution_role.name
  policy_arn = aws_iam_policy.ecs_execution_policy.arn
}

# ECS Web Task Role - for web service application permissions
resource "aws_iam_role" "ecs_web_task_role" {
  name                 = "${var.project_name}-${var.environment}-ecs-web-task-role"
  max_session_duration = 3600
  
  assume_role_policy = data.aws_iam_policy_document.ecs_assume_role.json
  
  tags = var.tags
}

data "aws_iam_policy_document" "ecs_web_task" {
  statement {
    effect = "Allow"
    actions = [
      "s3:GetObject"
    ]
    resources = ["arn:aws:s3:::${var.project_name}-${var.environment}-web/*"]
    
    condition {
      test     = "StringEquals"
      variable = "s3:RequestObjectTag/Environment"
      values   = [var.environment]
    }
  }
  
  statement {
    effect = "Allow"
    actions = [
      "secretsmanager:GetSecretValue"
    ]
    resources = ["arn:aws:secretsmanager:${data.aws_region.current.name}:${data.aws_caller_identity.current.account_id}:secret:${var.project_name}/${var.environment}/web/*"]
  }
}

resource "aws_iam_policy" "ecs_web_task_policy" {
  name        = "${var.project_name}-${var.environment}-ecs-web-task-policy"
  description = "Least privilege policy for ECS web tasks"
  
  policy = data.aws_iam_policy_document.ecs_web_task.json
  
  tags = var.tags
}

resource "aws_iam_role_policy_attachment" "ecs_web_task_policy_attachment" {
  role       = aws_iam_role.ecs_web_task_role.name
  policy_arn = aws_iam_policy.ecs_web_task_policy.arn
}

# ECS API Task Role - for API service application permissions
resource "aws_iam_role" "ecs_api_task_role" {
  name                 = "${var.project_name}-${var.environment}-ecs-api-task-role"
  max_session_duration = 3600
  
  assume_role_policy = data.aws_iam_policy_document.ecs_assume_role.json
  
  tags = var.tags
}

data "aws_iam_policy_document" "ecs_api_task" {
  statement {
    effect = "Allow"
    actions = [
      "s3:GetObject",
      "s3:PutObject"
    ]
    resources = ["arn:aws:s3:::${var.project_name}-${var.environment}-api/*"]
    
    condition {
      test     = "StringEquals"
      variable = "s3:RequestObjectTag/Environment"
      values   = [var.environment]
    }
  }
  
  statement {
    effect = "Allow"
    actions = [
      "secretsmanager:GetSecretValue"
    ]
    resources = ["arn:aws:secretsmanager:${data.aws_region.current.name}:${data.aws_caller_identity.current.account_id}:secret:${var.project_name}/${var.environment}/api/*"]
  }
  
  statement {
    effect = "Allow"
    actions = [
      "ssm:GetParameter",
      "ssm:GetParameters"
    ]
    resources = ["arn:aws:ssm:${data.aws_region.current.name}:${data.aws_caller_identity.current.account_id}:parameter/${var.project_name}/${var.environment}/api/*"]
    
    condition {
      test     = "StringEquals"
      variable = "ssm:GetParameter.Overwrite"
      values   = ["false"]
    }
  }
}

resource "aws_iam_policy" "ecs_api_task_policy" {
  name        = "${var.project_name}-${var.environment}-ecs-api-task-policy"
  description = "Least privilege policy for ECS API tasks"
  
  policy = data.aws_iam_policy_document.ecs_api_task.json
  
  tags = var.tags
}

resource "aws_iam_role_policy_attachment" "ecs_api_task_policy_attachment" {
  role       = aws_iam_role.ecs_api_task_role.name
  policy_arn = aws_iam_policy.ecs_api_task_policy.arn
}

# Auto Scaling Role for ECS
resource "aws_iam_role" "ecs_autoscaling_role" {
  name                 = "${var.project_name}-${var.environment}-ecs-autoscaling-role"
  max_session_duration = 3600
  
  assume_role_policy = data.aws_iam_policy_document.ecs_autoscaling_assume_role.json
  
  tags = var.tags
}

data "aws_iam_policy_document" "ecs_autoscaling_assume_role" {
  statement {
    effect = "Allow"
    
    principals {
      type        = "Service"
      identifiers = ["application-autoscaling.amazonaws.com"]
    }
    
    actions = ["sts:AssumeRole"]
  }
}

data "aws_iam_policy_document" "ecs_autoscaling" {
  statement {
    effect = "Allow"
    actions = [
      "ecs:DescribeServices",
      "ecs:UpdateService"
    ]
    resources = ["arn:aws:ecs:${data.aws_region.current.name}:${data.aws_caller_identity.current.account_id}:service/${var.project_name}-${var.environment}-*"]
  }
  
  statement {
    effect = "Allow"
    actions = [
      "cloudwatch:DescribeAlarms",
      "cloudwatch:GetMetricStatistics"
    ]
    resources = ["arn:aws:cloudwatch:${data.aws_region.current.name}:${data.aws_caller_identity.current.account_id}:alarm:${var.project_name}-${var.environment}-*"]
  }
}

resource "aws_iam_policy" "ecs_autoscaling_policy" {
  name        = "${var.project_name}-${var.environment}-ecs-autoscaling-policy"
  description = "Policy for ECS autoscaling"
  
  policy = data.aws_iam_policy_document.ecs_autoscaling.json
  
  tags = var.tags
}

resource "aws_iam_role_policy_attachment" "ecs_autoscaling_policy_attachment" {
  role       = aws_iam_role.ecs_autoscaling_role.name
  policy_arn = aws_iam_policy.ecs_autoscaling_policy.arn
}

# ============================================================================
# IAM Module Variables - modules/iam/variables.tf
# ============================================================================

variable "environment" {
  description = "Environment name"
  type        = string
}

variable "project_name" {
  description = "Project name"
  type        = string
}

variable "tags" {
  description = "Tags to apply to resources"
  type        = map(string)
  default     = {}
}

# ============================================================================
# IAM Module Outputs - modules/iam/outputs.tf
# ============================================================================

output "ecs_execution_role_arn" {
  description = "ARN of the ECS execution role"
  value       = aws_iam_role.ecs_execution_role.arn
}

output "ecs_web_task_role_arn" {
  description = "ARN of the ECS web task role"
  value       = aws_iam_role.ecs_web_task_role.arn
}

output "ecs_api_task_role_arn" {
  description = "ARN of the ECS API task role"
  value       = aws_iam_role.ecs_api_task_role.arn
}

output "ecs_autoscaling_role_arn" {
  description = "ARN of the ECS autoscaling role"
  value       = aws_iam_role.ecs_autoscaling_role.arn
}

# ============================================================================
# CloudFront Module - modules/cloudfront/main.tf
# ============================================================================

terraform {
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
}

resource "random_password" "origin_header" {
  length  = 32
  special = false
}

resource "aws_cloudfront_distribution" "main" {
  origin {
    domain_name = var.alb_dns_name
    origin_id   = "${var.project_name}-${var.environment}-alb"
    
    custom_origin_config {
      http_port              = 80
      https_port             = 443
      origin_protocol_policy = "https-only"
      origin_ssl_protocols   = ["TLSv1.2"]
    }
    
    custom_header {
      name  = "X-Origin-Verify"
      value = random_password.origin_header.result
    }
  }
  
  enabled             = true
  is_ipv6_enabled     = true
  comment             = "${var.project_name} ${var.environment} CloudFront distribution"
  default_root_object = "index.html"
  
  default_cache_behavior {
    allowed_methods        = ["DELETE", "GET", "HEAD", "
# Reference infrastructure for the secure RAG copilot on Azure.
# Security designed in: private endpoints, managed identity (no keys), Key Vault,
# APIM as the AI gateway with token quotas, diagnostic logs to Log Analytics.
# This is a reference skeleton: review SKUs, regions and naming before applying.

terraform {
  required_version = ">= 1.6"
  required_providers {
    azurerm = { source = "hashicorp/azurerm", version = "~> 4.0" }
  }
}

provider "azurerm" {
  features {}
}

locals {
  name = "${var.prefix}-${var.environment}"
  tags = { workload = "support-copilot", environment = var.environment, data_classification = "confidential" }
}

resource "azurerm_resource_group" "rg" {
  name     = "rg-${local.name}"
  location = var.location
  tags     = local.tags
}

# ---------------- network: everything private ----------------
resource "azurerm_virtual_network" "vnet" {
  name                = "vnet-${local.name}"
  address_space       = ["10.40.0.0/16"]
  location            = azurerm_resource_group.rg.location
  resource_group_name = azurerm_resource_group.rg.name
  tags                = local.tags
}

resource "azurerm_subnet" "apps" {
  name                 = "snet-apps"
  resource_group_name  = azurerm_resource_group.rg.name
  virtual_network_name = azurerm_virtual_network.vnet.name
  address_prefixes     = ["10.40.1.0/24"]
}

resource "azurerm_subnet" "endpoints" {
  name                 = "snet-private-endpoints"
  resource_group_name  = azurerm_resource_group.rg.name
  virtual_network_name = azurerm_virtual_network.vnet.name
  address_prefixes     = ["10.40.2.0/24"]
}

# ---------------- identity ----------------
resource "azurerm_user_assigned_identity" "app" {
  name                = "id-${local.name}-app"
  location            = azurerm_resource_group.rg.location
  resource_group_name = azurerm_resource_group.rg.name
}

# ---------------- Azure OpenAI: no public access, no local auth (keys) ----------------
resource "azurerm_cognitive_account" "openai" {
  name                          = "oai-${local.name}"
  location                      = azurerm_resource_group.rg.location
  resource_group_name           = azurerm_resource_group.rg.name
  kind                          = "OpenAI"
  sku_name                      = "S0"
  custom_subdomain_name         = "oai-${local.name}"
  public_network_access_enabled = false
  local_auth_enabled            = false
  tags                          = local.tags
}

resource "azurerm_cognitive_deployment" "chat" {
  name                 = "chat-prod"
  cognitive_account_id = azurerm_cognitive_account.openai.id
  model {
    format  = "OpenAI"
    name    = var.chat_model
    version = var.chat_model_version # pinned: model versions are part of the release
  }
  sku {
    name     = "Standard"
    capacity = var.tpm_thousands
  }
}

resource "azurerm_role_assignment" "app_openai_user" {
  scope                = azurerm_cognitive_account.openai.id
  role_definition_name = "Cognitive Services OpenAI User"
  principal_id         = azurerm_user_assigned_identity.app.principal_id
}

resource "azurerm_private_endpoint" "openai" {
  name                = "pe-oai-${local.name}"
  location            = azurerm_resource_group.rg.location
  resource_group_name = azurerm_resource_group.rg.name
  subnet_id           = azurerm_subnet.endpoints.id
  private_service_connection {
    name                           = "oai"
    private_connection_resource_id = azurerm_cognitive_account.openai.id
    subresource_names              = ["account"]
    is_manual_connection           = false
  }
}

# ---------------- Azure AI Search: security trimming via group filters ----------------
resource "azurerm_search_service" "search" {
  name                          = "srch-${local.name}"
  location                      = azurerm_resource_group.rg.location
  resource_group_name           = azurerm_resource_group.rg.name
  sku                           = "standard"
  public_network_access_enabled = false
  local_authentication_enabled  = false
  tags                          = local.tags
}

resource "azurerm_role_assignment" "app_search_reader" {
  scope                = azurerm_search_service.search.id
  role_definition_name = "Search Index Data Reader"
  principal_id         = azurerm_user_assigned_identity.app.principal_id
}

resource "azurerm_private_endpoint" "search" {
  name                = "pe-srch-${local.name}"
  location            = azurerm_resource_group.rg.location
  resource_group_name = azurerm_resource_group.rg.name
  subnet_id           = azurerm_subnet.endpoints.id
  private_service_connection {
    name                           = "search"
    private_connection_resource_id = azurerm_search_service.search.id
    subresource_names              = ["searchService"]
    is_manual_connection           = false
  }
}

# ---------------- Key Vault: RBAC, purge protection, private ----------------
data "azurerm_client_config" "current" {}

resource "azurerm_key_vault" "kv" {
  name                          = "kv-${replace(local.name, "-", "")}"
  location                      = azurerm_resource_group.rg.location
  resource_group_name           = azurerm_resource_group.rg.name
  tenant_id                     = data.azurerm_client_config.current.tenant_id
  sku_name                      = "standard"
  enable_rbac_authorization     = true
  purge_protection_enabled      = true
  public_network_access_enabled = false
  tags                          = local.tags
}

# ---------------- observability: prompt & response audit, cost, quality ----------------
resource "azurerm_log_analytics_workspace" "law" {
  name                = "law-${local.name}"
  location            = azurerm_resource_group.rg.location
  resource_group_name = azurerm_resource_group.rg.name
  retention_in_days   = var.log_retention_days
  tags                = local.tags
}

resource "azurerm_application_insights" "ai" {
  name                = "appi-${local.name}"
  location            = azurerm_resource_group.rg.location
  resource_group_name = azurerm_resource_group.rg.name
  workspace_id        = azurerm_log_analytics_workspace.law.id
  application_type    = "web"
}

resource "azurerm_monitor_diagnostic_setting" "openai" {
  name                       = "diag-oai"
  target_resource_id         = azurerm_cognitive_account.openai.id
  log_analytics_workspace_id = azurerm_log_analytics_workspace.law.id
  enabled_log { category_group = "audit" }
  metric { category = "AllMetrics" }
}

# ---------------- APIM as AI gateway (token quotas defined in policy) ----------------
resource "azurerm_api_management" "gateway" {
  name                 = "apim-${local.name}"
  location             = azurerm_resource_group.rg.location
  resource_group_name  = azurerm_resource_group.rg.name
  publisher_name       = var.publisher_name
  publisher_email      = var.publisher_email
  sku_name             = "Developer_1"
  virtual_network_type = "Internal"
  virtual_network_configuration { subnet_id = azurerm_subnet.apps.id }
  identity {
    type         = "UserAssigned"
    identity_ids = [azurerm_user_assigned_identity.app.id]
  }
  tags = local.tags
}

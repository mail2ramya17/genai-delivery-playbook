variable "prefix" {
  type    = string
  default = "copilot"
}

variable "environment" {
  type        = string
  description = "dev | test | prod"
  default     = "dev"
  validation {
    condition     = contains(["dev", "test", "prod"], var.environment)
    error_message = "environment must be dev, test or prod"
  }
}

variable "location" {
  type        = string
  default     = "eastus2"
  description = "Pick a region that satisfies data residency requirements."
}

variable "chat_model" {
  type    = string
  default = "gpt-4o"
}

variable "chat_model_version" {
  type    = string
  default = "2024-11-20"
}

variable "tpm_thousands" {
  type    = number
  default = 30
}

variable "log_retention_days" {
  type        = number
  default     = 90
  description = "Prompt/response log retention agreed with privacy & legal."
}

variable "publisher_name" {
  type    = string
  default = "AI Platform Team"
}

variable "publisher_email" {
  type    = string
  default = "ai-platform@example.com"
}

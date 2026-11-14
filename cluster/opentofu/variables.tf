variable "name_prefix" {
  description = "Prefix for every resource name, so they are easy to find in the dashboard."
  type        = string
  default     = "hons"
}

variable "ssh_allowed_cidrs" {
  description = "Address ranges allowed to SSH into the tooling VM."
  type        = list(string)

  validation {
    condition     = length(var.ssh_allowed_cidrs) > 0 && alltrue([for c in var.ssh_allowed_cidrs : can(cidrhost(c, 0))])
    error_message = "Give at least one range, each in CIDR form such as \"203.0.113.7/32\"."
  }
}

variable "public_key_path" {
  description = "Path to your SSH public key."
  type        = string
  default     = "~/.ssh/id_ed25519.pub"
}

variable "network_name" {
  description = "Existing private network of the project."
  type        = string
  default     = "ctb-gerope-network"
}

variable "floating_ip_pool" {
  description = "Name of the external network used to allocate floating IPs."
  type        = string
  default     = "Public-Network"
}

variable "image_name" {
  description = "Operating system image."
  type        = string
  default     = "Ubuntu-24.04-x64-2025-08"
}

variable "data_node_count" {
  description = "Number of Elasticsearch data VMs."
  type        = number
  default     = 4
}

variable "data_flavor" {
  description = "VM size for the data VMs."
  type        = string
  default     = "cb1-3.5gb-35"
}

variable "tooling_flavor" {
  description = "VM size for the tooling VM."
  type        = string
  default     = "cb1-3.5gb-35"
}

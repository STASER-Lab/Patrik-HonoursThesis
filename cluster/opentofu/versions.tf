# Which OpenTofu and provider versions this configuration needs.

terraform {
  required_version = ">= 1.8"

  required_providers {
    openstack = {
      source  = "terraform-provider-openstack/openstack"
      version = "~> 3.0"
    }
  }
}

provider "openstack" {}

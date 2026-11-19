# Object storage bucket for Elasticsearch snapshots.

variable "bucket_name" {
  description = "Must be unique across all of Arbutus object storage."
  type        = string
  default     = "ctb-gerope-hons-snapshots"
}

resource "openstack_objectstorage_container_v1" "snapshots" {
  name = var.bucket_name

  lifecycle {
    prevent_destroy = true
  }
}

output "bucket_name" {
  value = openstack_objectstorage_container_v1.snapshots.name
}

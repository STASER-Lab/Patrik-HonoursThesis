# The experiment cluster.

# --- Look up existing OpenStack resources -------------------------------------

data "openstack_networking_network_v2" "private" {
  name = var.network_name
}

data "openstack_images_image_v2" "ubuntu" {
  name        = var.image_name
  most_recent = true
}

data "openstack_compute_flavor_v2" "data" {
  name = var.data_flavor
}

data "openstack_compute_flavor_v2" "tooling" {
  name = var.tooling_flavor
}

# --- Access -------------------------------------------------------------------

resource "openstack_compute_keypair_v2" "admin" {
  name       = "${var.name_prefix}-admin"
  public_key = file(pathexpand(var.public_key_path))
}

# --- Firewall -----------------------------------------------------------------

resource "openstack_networking_secgroup_v2" "ssh" {
  name        = "${var.name_prefix}-ssh"
  description = "SSH from the admin's addresses only"
}

# One rule per allowed address range.
resource "openstack_networking_secgroup_rule_v2" "ssh_in" {
  for_each          = toset(var.ssh_allowed_cidrs)
  security_group_id = openstack_networking_secgroup_v2.ssh.id
  direction         = "ingress"
  ethertype         = "IPv4"
  protocol          = "tcp"
  port_range_min    = 22
  port_range_max    = 22
  remote_ip_prefix  = each.value
}

resource "openstack_networking_secgroup_v2" "cluster" {
  name        = "${var.name_prefix}-cluster"
  description = "All traffic between cluster VMs"
}

resource "openstack_networking_secgroup_rule_v2" "cluster_in" {
  security_group_id = openstack_networking_secgroup_v2.cluster.id
  direction         = "ingress"
  ethertype         = "IPv4"
  remote_group_id   = openstack_networking_secgroup_v2.cluster.id
}

# --- Placement ----------------------------------------------------------------

# Anti-affinity: OpenStack must put each data VM on a different physical server.
resource "openstack_compute_servergroup_v2" "data" {
  name     = "${var.name_prefix}-data"
  policies = ["anti-affinity"]
}

# --- Data VMs -----------------------------------------------------------------

resource "openstack_networking_port_v2" "data" {
  count              = var.data_node_count
  name               = "${var.name_prefix}-data-${count.index + 1}"
  network_id         = data.openstack_networking_network_v2.private.id
  security_group_ids = [openstack_networking_secgroup_v2.cluster.id]
}

resource "openstack_compute_instance_v2" "data" {
  count     = var.data_node_count
  name      = "${var.name_prefix}-data-${count.index + 1}"
  image_id  = data.openstack_images_image_v2.ubuntu.id
  flavor_id = data.openstack_compute_flavor_v2.data.id
  key_pair  = openstack_compute_keypair_v2.admin.name
  user_data = file("${path.module}/cloud-init.yaml")

  network {
    port = openstack_networking_port_v2.data[count.index].id
  }

  scheduler_hints {
    group = openstack_compute_servergroup_v2.data.id
  }
}

# --- Tooling VM ---------------------------------------------------------------

resource "openstack_networking_port_v2" "tooling" {
  name       = "${var.name_prefix}-tooling"
  network_id = data.openstack_networking_network_v2.private.id
  security_group_ids = [
    openstack_networking_secgroup_v2.cluster.id,
    openstack_networking_secgroup_v2.ssh.id,
  ]
}

resource "openstack_compute_instance_v2" "tooling" {
  name      = "${var.name_prefix}-tooling"
  image_id  = data.openstack_images_image_v2.ubuntu.id
  flavor_id = data.openstack_compute_flavor_v2.tooling.id
  key_pair  = openstack_compute_keypair_v2.admin.name
  user_data = file("${path.module}/cloud-init.yaml")

  network {
    port = openstack_networking_port_v2.tooling.id
  }
}

resource "openstack_networking_floatingip_v2" "tooling" {
  pool = var.floating_ip_pool
}

resource "openstack_networking_floatingip_associate_v2" "tooling" {
  floating_ip = openstack_networking_floatingip_v2.tooling.address
  port_id     = openstack_networking_port_v2.tooling.id
}

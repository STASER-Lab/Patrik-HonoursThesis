# Printed after `tofu apply`.

output "tooling_public_ip" {
  value = openstack_networking_floatingip_v2.tooling.address
}

output "tooling_private_ip" {
  value = openstack_networking_port_v2.tooling.all_fixed_ips[0]
}

output "data_private_ips" {
  value = { for i, p in openstack_networking_port_v2.data : "${var.name_prefix}-data-${i + 1}" => p.all_fixed_ips[0] }
}

output "ssh_tooling" {
  value = "ssh ubuntu@${openstack_networking_floatingip_v2.tooling.address}"
}

output "ssh_data" {
  value = { for i, p in openstack_networking_port_v2.data : "${var.name_prefix}-data-${i + 1}" => "ssh -J ubuntu@${openstack_networking_floatingip_v2.tooling.address} ubuntu@${p.all_fixed_ips[0]}" }
}

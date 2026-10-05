# Open Virtual Network (OVN) & Open vSwitch (OVS): Student Lab Workbook

Welcome to the OVN and OVS classroom lab! In this workbook, you will learn how to build, secure, and route traffic in virtual networks. We will start from zero, assuming you have never touched OVN before. 

> **How to use this workbook:** Work through the modules in order. Commands
> change a shared network database, so use a disposable classroom OVN
> deployment or an instructor-provided lab. Do not run configuration or
> cleanup commands on a production or shared cloud. Complete the questions
> before reading the answer hints at the end of each module.

## Before the First Command: The Lab and Its Vocabulary

### What you are building

The examples in this workbook describe one tenant network:

| Name | Purpose | Example address |
| --- | --- | --- |
| `sw-tenant1` | Tenant subnet 1 | `10.0.1.0/24` |
| `sw-tenant2` | Tenant subnet 2 | `10.0.2.0/24` |
| `router-tenant` | Connects the tenant subnets to each other and, later, outside | — |
| `port-vm-a` | Example VM interface on subnet 1 | `10.0.1.10` |
| `port-vm-b` | Second example VM interface on subnet 1 | `10.0.1.20` |
| `port-vm-c` | Example VM interface on subnet 2 | `10.0.2.10` |

These are **example logical ports**, not VMs. Creating an OVN logical port
does not create a virtual machine, configure its operating system, or plug an
interface into OVS. A guest needs a real virtual NIC attached to the correct
OVS integration bridge, and that interface must identify its OVN port. The
examples using `ovn-trace` model packets and do not send traffic onto a wire.

### Where commands run

There are two command contexts in a real deployment:

1. **OVN database client:** Run `ovn-nbctl`, `ovn-sbctl`, and `ovn-trace` on a
   machine that can reach the OVN databases. These commands read or change
   OVN's logical or control-plane state.
2. **OVS chassis:** Run `ovs-vsctl`, `ovs-ofctl`, and `ovs-appctl` on a host
   that runs Open vSwitch. These commands inspect or configure the local
   switch. Commands that change a bridge or physical interface can interrupt
   connectivity; in this workbook, OVS inspection commands are read-only.

The prompt in your classroom lab may put these tools in a container or provide
wrappers. Follow the instructor's connection instructions. If your database
is remote, use the same database options consistently, for example:

```bash
ovn-nbctl --db=tcp:10.0.0.10:6641 show
ovn-sbctl --db=tcp:10.0.0.10:6642 show
ovn-trace --db=tcp:10.0.0.10:6641 --summary sw-tenant1 'inport == "port-vm-a"'
```

Replace the example database address with the one supplied by the instructor.
Do not copy these IP addresses unless they are actually assigned in your lab.

### A short glossary

* **Packet:** A unit of network data. IP packets are carried inside Ethernet
  frames on a local network.
* **MAC address:** An Ethernet address such as `50:54:00:00:00:0A`. A switch
  uses it for local Layer 2 delivery.
* **IP address and subnet:** An address such as `10.0.1.10/24`. The `/24`
  prefix says which addresses are on the same IP subnet.
* **Port:** An attachment point. An OVN logical port describes a desired
  attachment; an OVS interface is a host's actual attachment.
* **Datapath:** In `ovn-trace`, the logical switch or router where a packet
  starts.
* **Microflow:** The packet fields supplied to `ovn-trace` to describe one
  hypothetical packet: ingress port, Ethernet addresses, IP addresses, and
  protocol fields.
* **Control plane / data plane:** The control plane stores and distributes
  network intent. The data plane forwards actual packets. A successful
  `ovn-nbctl` change proves the database accepted the intent; by itself, it
  does not prove a guest can communicate.

### Check the tools and database before changing anything

Run these read-only checks first:

```bash
ovn-nbctl --version
ovn-sbctl --version
ovn-trace --version
ovs-vsctl --version
ovn-nbctl show
ovn-sbctl show
```

`ovn-nbctl show` prints logical switches, their ports, logical routers, and
their ports. `ovn-sbctl show` prints the chassis known to the Southbound
database. In an empty training deployment the output may be small; if the
database already contains objects, ask the instructor which names are safe to
use before proceeding. Record the OVN and OVS versions because supported
features and output details vary by release.

**Checkpoint:** Which command shows logical intent? Which one shows chassis?
Which one inspects the local OVS instance? Write down the answers before
continuing.

## Introduction: What are OVS and OVN?

Before we type any commands, we need to understand the relationship between OVS and OVN.

*   **Open vSwitch (OVS):** A software switch installed on a host. That host is
    often called a hypervisor or, in OVN terminology, a **chassis**. OVS
    forwards real packets using flow tables.
*   **Open Virtual Network (OVN):** A network control plane that adds logical
    switches, routers, DHCP, ACLs, NAT, and other network abstractions. You
    describe the intended network in OVN; OVN translates that intent into
    logical flows and distributes the work to OVS chassis.
*   **`ovn-controller`:** The OVN agent on each chassis. It reads the
    Southbound database and programs that chassis's local OVS instance.
*   **`ovn-northd`:** The central translation service. It watches the
    Northbound database and translates its logical configuration into
    Southbound state for the chassis agents.

OVN does not replace OVS. OVS is the local switching/data-plane component;
OVN coordinates the network-wide logical behavior. A logical router is not
necessarily a separate physical router appliance: OVN can distribute its
logical routing work across chassis.

OVN has two main databases, plus the local OVS instance on each chassis:
1.  **Northbound Database (NB DB):** The logical configuration: logical
    switches, ports, routers, routes, NAT, DHCP, and ACLs. Use `ovn-nbctl` to
    inspect or change it.
2.  **Southbound Database (SB DB):** The translated state used by chassis:
    chassis, port bindings, and logical flow information. Use `ovn-sbctl` to
    inspect it.
3.  **Local OVS:** The switch on an individual chassis. Use `ovs-vsctl` to
    inspect bridges and interfaces, and `ovs-ofctl` to inspect OpenFlow.

There are multiple kinds of "flow" in this system. OVN logical flows express
network behavior in OVN's pipeline; OVS OpenFlow rules implement that behavior
on a particular chassis. `ovn-trace` traces the **logical pipeline**. It is
not a packet capture and does not prove that a real physical NIC, tunnel, or
guest interface is working.

In these exercises, we will act as cloud administrators: `ovn-nbctl` builds
the logical network, `ovn-sbctl` helps us inspect its distributed state,
`ovn-trace` simulates packets through the logical pipeline, and selected OVS
commands let us inspect the local data plane.

---

## Module 1: The Basics - Layer 2 Logical Switching

### The Concept
A **Logical Switch** is a virtual equivalent of a physical Ethernet switch. Even if your VMs are on different physical servers across the world, if they are attached to the same OVN Logical Switch, they think they are plugged into the same physical hardware switch. They can talk to each other using Layer 2 MAC addresses.

Under the hood, OVN creates a hidden integration bridge in OVS (usually named `br-int`). When a VM boots up, its virtual network interface (VIF) is plugged into this OVS bridge.

### The Exercise: Create a Switch and Attach Ports
Let's create our first network for two virtual machines (VM-A and VM-B).

**Step 1. Create the Logical Switch**
We will call it `sw-tenant1`.
```bash
ovn-nbctl ls-add sw-tenant1
```

**Step 2. Create Logical Ports**
A switch is useless without ports. Let's create two ports on `sw-tenant1`.
```bash
ovn-nbctl lsp-add sw-tenant1 port-vm-a
ovn-nbctl lsp-add sw-tenant1 port-vm-b
```

**Step 3. Assign MAC and IP Addresses**
Unlike a physical switch, a logical switch needs to know what MAC and IP addresses belong to which port so it can optimize routing and prevent spoofing. Let's assign them.
```bash
# Format: "MAC_ADDRESS IP_ADDRESS"
ovn-nbctl lsp-set-addresses port-vm-a "50:54:00:00:00:0A 10.0.1.10"
ovn-nbctl lsp-set-addresses port-vm-b "50:54:00:00:00:0B 10.0.1.20"
```

**Step 4. Verify the Configuration**
Let's view our Northbound database configuration.
```bash
ovn-nbctl show
ovn-nbctl list Logical_Switch
ovn-nbctl list Logical_Switch_Port
```
`show` prints the logical topology; the `list` commands show the underlying
database rows. Find the row named `sw-tenant1`, then find both port rows.

*Student Check:* Do both ports belong to `sw-tenant1`? Do their configured
addresses match the table at the start of the workbook?

**Step 5. Read the result**

The switch is a logical object in the NB database. OVN has not created two
guest operating systems. In a real deployment, a VM manager must create each
VM and attach its NIC to a host's OVS integration bridge. The attached
interface must carry the OVN logical-port identity, commonly as the OVS
Interface external ID `iface-id=port-vm-a`. That step is deliberately not
performed in this logical-only exercise.

*Think about it:* If `ovn-nbctl show` lists the port but there is no matching
interface on any host, what do you expect to find in the SB Port_Binding
table?

---

## Module 2: Port Security and Anti-Spoofing

### The Concept
In a cloud environment, you cannot trust the virtual machines. A malicious user on VM-A might try to change their IP address to `10.0.1.20` to steal VM-B's traffic. OVN can program OVS to drop any packets from a port that do not match the assigned MAC and IP addresses.

### The Exercise: Enforce Port Security

**Step 1. Enable Port Security**
We apply port security by telling the port exactly which addresses are allowed to enter the switch from that port.
```bash
ovn-nbctl lsp-set-port-security port-vm-a "50:54:00:00:00:0A 10.0.1.10"
ovn-nbctl lsp-set-port-security port-vm-b "50:54:00:00:00:0B 10.0.1.20"
```

**Step 2. Test the Network (Simulation)**
Since we don't have real VMs running, we use `ovn-trace` to inject a fake packet into the logical network. We are going to simulate a ping (ICMP) from VM-A to VM-B.

```bash
ovn-trace --summary sw-tenant1 'inport == "port-vm-a" && eth.src == 50:54:00:00:00:0A && eth.dst == 50:54:00:00:00:0B && ip4.src == 10.0.1.10 && ip4.dst == 10.0.1.20'
```
*Student Check:* Follow the trace to its final action. For a packet that
matches the source port's permitted addresses and reaches its destination, the
summary should show output toward `port-vm-b`.

This is a logical simulation. There does not need to be a running VM, but the
trace also does not demonstrate that a real VM is plugged into OVS.

**Step 3. Test the Security (The Hacker Simulation)**
Now, simulate VM-A trying to spoof its source IP address as `10.0.1.99`. Modify `ip4.src` in the trace:
```bash
ovn-trace --summary sw-tenant1 'inport == "port-vm-a" && eth.src == 50:54:00:00:00:0A && eth.dst == 50:54:00:00:00:0B && ip4.src == 10.0.1.99 && ip4.dst == 10.0.1.20'
```
*Student Check:* Find the drop in the trace. OVN releases differ in how they
format summaries, so do not rely on an empty output. The key result is that the
packet does **not** reach `port-vm-b`.

Port security is an ingress check: OVN checks whether the Ethernet/IP source
fields are permitted on the port where the packet entered. It is distinct
from an ACL, which is a switch policy that matches packets in a particular
direction and at a particular priority.

*Discussion:* What changes if you keep the allowed IP but change only the
Ethernet source MAC? Test it by changing `eth.src` and compare the trace.

---

## Module 3: Distributed Logical Routing (Layer 3)

### The Concept
If VM-A (`10.0.1.10`) needs to talk to a new machine, VM-C (`10.0.2.10`), they are on different subnets. A Layer 2 switch cannot bridge them; they need a router. 

Traditional routers are bottlenecks—all traffic goes to one physical appliance. OVN uses **Distributed Logical Routers**. OVN programs OVS so that the routing decision is made on the hypervisor *where the VM lives*. If VM-A pings VM-C, VM-A's local OVS acts as the router, rewrites the MAC addresses, and sends it directly to VM-C's server.

### The Exercise: Connect Two Subnets

**Step 1. Create a Second Switch and Port**
```bash
ovn-nbctl ls-add sw-tenant2
ovn-nbctl lsp-add sw-tenant2 port-vm-c
ovn-nbctl lsp-set-addresses port-vm-c "50:54:00:00:00:0C 10.0.2.10"
ovn-nbctl lsp-set-port-security port-vm-c "50:54:00:00:00:0C 10.0.2.10"
```

**Step 2. Create the Logical Router**
```bash
ovn-nbctl lr-add router-tenant
```

**Step 3. Connect Switch 1 to the Router**
Connecting a switch to a router requires two ports linked together like a patch cable: a port on the router, and a port on the switch.

Create the port on the router (requires a MAC and the gateway IP/Subnet):
```bash
ovn-nbctl lrp-add router-tenant rtr-to-sw1 00:00:00:00:01:FF 10.0.1.1/24
```
Create the port on the switch and link it to the router port:
```bash
ovn-nbctl lsp-add sw-tenant1 sw1-to-rtr
ovn-nbctl lsp-set-type sw1-to-rtr router
ovn-nbctl lsp-set-addresses sw1-to-rtr router
ovn-nbctl lsp-set-options sw1-to-rtr router-port=rtr-to-sw1
```

**Step 4. Connect Switch 2 to the Router**
Repeat the process for the second subnet.
```bash
ovn-nbctl lrp-add router-tenant rtr-to-sw2 00:00:00:00:02:FF 10.0.2.1/24

ovn-nbctl lsp-add sw-tenant2 sw2-to-rtr
ovn-nbctl lsp-set-type sw2-to-rtr router
ovn-nbctl lsp-set-addresses sw2-to-rtr router
ovn-nbctl lsp-set-options sw2-to-rtr router-port=rtr-to-sw2
```

**Step 5. Trace the Route**
Let's send a packet from VM-A (`10.0.1.10`) to VM-C (`10.0.2.10`). Because it's a different subnet, VM-A will address the Ethernet frame to its default gateway's MAC address (`00:00:00:00:01:FF`).

```bash
ovn-trace --summary sw-tenant1 'inport == "port-vm-a" && eth.src == 50:54:00:00:00:0A && eth.dst == 00:00:00:00:01:FF && ip4.src == 10.0.1.10 && ip4.dst == 10.0.2.10 && ip.ttl == 64'
```
*Student Check:* Follow each logical stage. The packet should be routed from
`sw-tenant1` through `router-tenant` and toward `port-vm-c` on `sw-tenant2`.
OVN releases may format the stages differently. A router decrements the IPv4
TTL while forwarding.

This trace assumes VM-A already knows to send off-subnet traffic to
`10.0.1.1`, whose Ethernet address is `00:00:00:00:01:FF`. OVN does not
configure that default route inside a guest. A real guest needs an IP address,
subnet mask, and default gateway configured by its operating system or DHCP.
Similarly, `port-vm-c` describes the intended guest address but does not
configure VM-C.

**Challenge:** Change only `ip.ttl == 64` to `ip.ttl == 1`. Before running
the trace, predict whether the router can forward the packet. Then run it and
find the point where the packet stops.

---

## Module 4: Stateful Firewalling with Access Control Lists (ACLs)

### The Concept
Security Groups in clouds like OpenStack or AWS are implemented in OVN using Access Control Lists (ACLs). OVN translates ACLs into OVS connection tracking (`ct`) OpenFlow rules. "Stateful" means the firewall remembers established connections—if you allow an outbound HTTP request, it automatically allows the inbound HTTP response.

### The Exercise: Lock Down VM-C

Let's assume VM-C is a web server. We want to drop traffic addressed to it by
default, but allow TCP port 80 (HTTP) and ICMP (ping). These ACLs apply to
traffic delivered to `port-vm-c`; they are not a deny-all policy for every
port on the switch.

**Step 1. Allow Established Return Traffic**
Connection tracking (often abbreviated `ct`) lets OVN recognize packets that
belong to an already established connection. This higher-priority rule
permits established, non-related traffic to VM-C:
```bash
ovn-nbctl acl-add sw-tenant2 to-lport 3000 'outport == "port-vm-c" && ct.est && !ct.rel' allow-related
```
`to-lport` means the rule is evaluated on traffic being delivered to a
logical switch port. `outport` names that destination port. `ct.est` is the
connection-tracking established state. Read the rule aloud as:
"For packets going to VM-C that belong to an established connection, allow
them."

**Step 2. Allow Inbound Ping (ICMP)**
```bash
ovn-nbctl acl-add sw-tenant2 to-lport 2000 'outport == "port-vm-c" && icmp4' allow-related
```

**Step 3. Allow Inbound Web Traffic (TCP 80)**
```bash
ovn-nbctl acl-add sw-tenant2 to-lport 2000 'outport == "port-vm-c" && tcp.dst == 80' allow-related
```

**Step 4. Default Deny**
If a packet to VM-C matches none of the higher-priority rules, drop it. A
higher numeric priority is evaluated ahead of a lower one.
```bash
ovn-nbctl acl-add sw-tenant2 to-lport 1000 'outport == "port-vm-c"' drop
```

**Step 5. Test the Firewall**
Let's try to SSH (TCP port 22) from VM-A to VM-C.
```bash
ovn-trace --minimal sw-tenant1 'inport == "port-vm-a" && eth.src == 50:54:00:00:00:0A && eth.dst == 00:00:00:00:01:FF && ip4.src == 10.0.1.10 && ip4.dst == 10.0.2.10 && tcp.dst == 22 && ip.ttl == 64'
```
*Student Check:* Find the drop action for TCP port 22. The trace output is
not necessarily empty; use its final logical action to decide whether the
packet was delivered.

Now change `tcp.dst == 22` to `tcp.dst == 80` and run the command again.
The TCP/80 rule should allow the packet to reach `port-vm-c`.

**Step 6. Test priority and scope**

Display the configured ACLs:

```bash
ovn-nbctl acl-list sw-tenant2
```

Change the test microflow to target a different destination port or a
different logical outport. Predict which rule matches before you run
`ovn-trace`. Then explain why a rule that matches `outport == "port-vm-c"`
does not block packets delivered to VM-B.

> **Classroom note:** ACL syntax and tracing details vary across OVN versions.
> If `ovn-nbctl acl-list` or a match field is rejected, consult the man page
> installed with your deployment rather than assuming a rule was installed.

---

## Module 5: External Connectivity and NAT

### The Concept
So far, our VMs can only talk to each other. To reach the Internet, traffic must leave the virtual OVN world and enter the physical network.
1.  **Localnet Port:** A special port on a logical switch that bridges the virtual switch directly to a physical network interface on the host via OVS.
2.  **NAT:** Private IPs (`10.0.1.10`) aren't allowed on the public Internet. The OVN router must perform Source NAT (SNAT) to translate the private IP into a public IP before it leaves.

### The Exercise: Connect to the World

> **Important prerequisite:** Creating an OVN `localnet` port does not
> configure a physical uplink. The lab operator must have already mapped
> `physnet1` to an OVS bridge on the chassis (for example, via the chassis
> `ovn-bridge-mappings` setting), and that bridge must have a working
> connection to the stated external VLAN/subnet and upstream router. Do not
> change host bridge mappings in a shared or production environment.

**Step 1. Create the External Switch and Localnet Port**
```bash
ovn-nbctl ls-add external-network

# Create the localnet port. This tells OVS to bridge this to a physical interface tagged 'physnet1'
ovn-nbctl lsp-add external-network ln-ext
ovn-nbctl lsp-set-type ln-ext localnet
ovn-nbctl lsp-set-addresses ln-ext unknown
ovn-nbctl lsp-set-options ln-ext network_name=physnet1
```

**Step 2. Connect the Router to the External Switch**
```bash
# Assign public IP 172.16.1.1 to the router's external interface
ovn-nbctl lrp-add router-tenant rtr-to-ext 00:01:20:20:12:13 172.16.1.1/24

ovn-nbctl lsp-add external-network ext-to-rtr
ovn-nbctl lsp-set-type ext-to-rtr router
ovn-nbctl lsp-set-addresses ext-to-rtr router
ovn-nbctl lsp-set-options ext-to-rtr router-port=rtr-to-ext
```

**Step 3. Add a Default Route**
Tell the router: "If you don't know where an IP is (like `8.8.8.8`), send it out the external port to the physical provider router at `172.16.1.254`."
```bash
ovn-nbctl lr-route-add router-tenant 0.0.0.0/0 172.16.1.254
```

**Step 4. Configure SNAT**
Translate all `10.0.1.0/24` traffic to the router's public IP `172.16.1.1`.
```bash
ovn-nbctl lr-nat-add router-tenant snat 172.16.1.1 10.0.1.0/24
```

**Step 5. Trace Outbound Internet Traffic**
Trace a packet from VM-A to Google DNS (`8.8.8.8`).
```bash
ovn-trace --summary sw-tenant1 'inport == "port-vm-a" && eth.src == 50:54:00:00:00:0A && eth.dst == 00:00:00:00:01:FF && ip4.src == 10.0.1.10 && ip4.dst == 8.8.8.8 && ip.ttl == 64'
```
*Student Check:* Follow the logical router's route and NAT actions. Depending
on the installed OVN version, the summary may name a translation action
differently; verify that the source is translated to `172.16.1.1` before
forwarding out the external logical network.

This trace proves only that OVN's logical pipeline has a route and NAT
configuration. It does **not** prove that the physical bridge mapping,
external VLAN, upstream route, return route, or firewall is working. In
addition, the example SNAT rule covers only `10.0.1.0/24`; traffic from
`10.0.2.0/24` needs its own NAT configuration if that subnet must use SNAT.

**Checkpoint:** Draw the packet's path in two colors: one for the logical
objects OVN knows about and one for the physical components an operator must
provide.

---

## Module 6: Policy-Based Routing (PBR)

### The Concept
Standard routing is destination-based (e.g., "Where is `10.0.2.10`?"). Policy-Based Routing (PBR) allows you to route traffic based on *source*, *protocol*, or *port*. 
Use Case: You want all web traffic (TCP 80) leaving VM-A to be routed through a deep-packet inspection appliance (Firewall VM) at `10.0.1.100`, rather than going straight to the destination.

### The Exercise: Reroute HTTP Traffic

**Step 1. Add the Policy**
Before adding the policy, create an example next-hop port on the same logical
subnet as VM-A. This provides a logical neighbor at `10.0.1.100`. It is only
an example attachment: to inspect or forward real packets, a firewall VM or
appliance must actually be plugged into this logical port and configured.

```bash
ovn-nbctl lsp-add sw-tenant1 port-firewall
ovn-nbctl lsp-set-addresses port-firewall "50:54:00:00:00:F0 10.0.1.100"
ovn-nbctl lsp-set-port-security port-firewall "50:54:00:00:00:F0 10.0.1.100"
```

We will add a policy to `router-tenant`. Priority 100 is the precedence
within the router's policy rules; policy routes are evaluated before ordinary
destination-based routing.
```bash
ovn-nbctl lr-policy-add router-tenant 100 'ip4.src == 10.0.1.10 && tcp.dst == 80' reroute 10.0.1.100
```

**Step 2. Test Normal Traffic vs Policy Traffic**
First, trace a normal ICMP ping to the outside world from VM-A:
```bash
ovn-trace --minimal sw-tenant1 'inport == "port-vm-a" && eth.src == 50:54:00:00:00:0A && eth.dst == 00:00:00:00:01:FF && ip4.src == 10.0.1.10 && ip4.dst == 8.8.8.8 && icmp4.type == 8 && ip.ttl == 64'
```
*Result:* It uses SNAT and goes out `ln-ext`.

Now, trace an HTTP request to the outside world:
```bash
ovn-trace --minimal sw-tenant1 'inport == "port-vm-a" && eth.src == 50:54:00:00:00:0A && eth.dst == 00:00:00:00:01:FF && ip4.src == 10.0.1.10 && ip4.dst == 8.8.8.8 && tcp.dst == 80 && ip.ttl == 64'
```
*Student Check:* The HTTP packet should be redirected toward the logical
next-hop port `port-firewall`, rather than sent straight to the external
network. Confirm the actual final actions in your trace.

PBR changes the selected next hop; it does not install or operate a firewall.
For real inspected traffic, the appliance must be running, attached to this
port, and able to forward or reject packets. Its return path must also be
designed. A packet leaving the VM is not automatically sent back through the
same appliance on the way to the VM.

**Challenge:** Add a second policy matching a different TCP destination port
and a different next hop. Use two priorities and predict which rule wins for a
packet matching both. Use `ovn-nbctl list Logical_Router_Policy` to inspect
the policy rows and compare their UUIDs with the policies referenced by
`router-tenant`.

---
---

## Module 7: Automatic Addressing with OVN IPAM and DHCP

### Learning goal

See the difference between assigning a fixed address to a logical port and
asking OVN to allocate an address. Then attach DHCP options so a real guest
can learn network settings automatically.

### The idea

**IPAM** means IP address management. In OVN, a logical switch can have a
subnet configured for dynamic address allocation. A logical port with
`addresses=dynamic` asks OVN to choose an address from that subnet.

DHCP is a protocol by which a client asks for network settings such as an IP
address, subnet mask, router, and DNS server. OVN can supply DHCP responses
for a configured logical port. This still does not boot a VM or make the VM
send a DHCP request: the VM needs a connected virtual NIC and a DHCP client.

Use a separate training switch for this exercise so the existing static
addresses on `sw-tenant1` cannot be confused with dynamic allocations.

### Exercise: allocate a dynamic address

**Step 1. Create the DHCP lab switch and configure its IPAM subnet.**

```bash
ovn-nbctl ls-add sw-dhcp
ovn-nbctl set Logical_Switch sw-dhcp other_config:subnet=192.0.2.0/24
```

The `set` command edits a column on an existing NB database row. Here it adds
the `subnet` key to the logical switch's `other_config` map. `192.0.2.0/24`
is reserved for examples and documentation; it is not an Internet-routable
address.

**Step 2. Add a logical port that requests a dynamic address.**

```bash
ovn-nbctl lsp-add sw-dhcp port-dynamic
ovn-nbctl lsp-set-addresses port-dynamic dynamic
```

The first command creates the logical attachment. The second asks OVN to
allocate the port's MAC and IP address from switch IPAM. The keyword
`dynamic` is literal configuration, not a shell variable.

**Step 3. Inspect the allocated address.**

```bash
ovn-nbctl get Logical_Switch_Port port-dynamic addresses
ovn-nbctl get Logical_Switch_Port port-dynamic dynamic_addresses
```

In a functioning deployment, OVN fills `dynamic_addresses` with the allocated
MAC and IP. A brief delay may be needed while `ovn-northd` processes the
change. If the value remains empty, inspect `ovn-nbctl show`, the NB switch
`other_config`, and the health of the OVN services before continuing.

**Step 4. Create DHCP options and attach them to the port.**

Run these commands in a Bash-compatible shell. The first prints the new
DHCP_Options row's UUID; the shell saves that value in `DHCP_UUID`.

```bash
DHCP_UUID=$(ovn-nbctl dhcp-options-create 192.0.2.0/24 \
  server_id=192.0.2.254 \
  server_mac=02:00:00:00:02:54 \
  lease_time=3600 \
  dns_server=192.0.2.53)
printf 'Created DHCP options row: %s\n' "$DHCP_UUID"
ovn-nbctl lsp-set-dhcpv4-options port-dynamic "$DHCP_UUID"
ovn-nbctl get Logical_Switch_Port port-dynamic dhcpv4_options
```

The example describes DHCP settings; it does not start a DNS server at
`192.0.2.53`. A real guest can receive that DNS address, but name lookups
will work only if an actual DNS service is reachable there.

**Step 5. Verify from both the logical and physical viewpoints.**

```bash
ovn-nbctl show
ovn-nbctl list DHCP_Options
ovn-sbctl show
ovn-sbctl list Port_Binding
```

The NB database should show the intended switch, port, allocated address,
and DHCP option reference. The SB database may have a port-binding row even
when the port is not attached to a running VM. Do not infer that a guest has
received a DHCP lease just from the presence of an NB DHCP configuration.

### Questions

1. Which command created the logical port, and which requested an address?
2. Which output is the address allocation, and which is the DHCP setting?
3. What extra evidence would you collect to prove a real guest received a
   lease?

**Answer hints:** Look for an address in `dynamic_addresses`; inspect the
port's `dhcpv4_options`; for an actual lease, check the guest's network
configuration or DHCP client logs.

---

## Module 8: Follow a Logical Port into the Southbound Database

### Learning goal

Understand how a logical port becomes associated with a physical host, and
why a logical port by itself is not a live VM connection.

### The idea

The VM manager creates a guest interface and connects it to the local OVS
integration bridge (commonly `br-int`). It associates the OVS Interface with
the OVN logical port, usually through the external ID `iface-id`. The local
`ovn-controller` reports the attachment through the SB database. OVN calls
the resulting association a **port binding**.

When you inspect the binding, compare the logical port name, chassis, and
port type. A missing chassis association can mean that no matching interface
is attached, that the agent has not processed it yet, or that the deployment
has a problem. It does not by itself tell you which cause applies.

### Exercise: inspect, do not alter, the data plane

**Step 1. Find the logical port in the NB database.**

```bash
ovn-nbctl find Logical_Switch_Port name=port-vm-a
```

This should return the NB row. This checks desired logical state, not an OVS
interface.

**Step 2. Look for the SB binding.**

```bash
ovn-sbctl --columns=logical_port,type,chassis,datapath list Port_Binding
```

Find the row whose `logical_port` is `port-vm-a`. If the classroom deployment
does not have a VM attached, the chassis field may be empty. That is a useful
observation rather than proof that the NB port failed to be created.

**Step 3. On a chassis, inspect OVS.**

Run these read-only commands on a host that runs OVS:

```bash
ovs-vsctl show
ovs-vsctl list-br
ovs-vsctl list-ports br-int
ovs-vsctl --columns=name,ofport,external_ids list Interface
```

Find the integration bridge and its interfaces. If a VM interface is
attached, inspect its `external_ids` and look for `iface-id=port-vm-a`.
The interface name may be generated by a hypervisor and need not be
`port-vm-a`.

**Step 4. Inspect the OVS forwarding rules.**

```bash
ovs-ofctl dump-flows br-int
```

This can produce a large output. Search for the logical port's OpenFlow port
or other identifiers shown by your deployment. OVN-generated rules are
implementation details and change between releases; do not expect one
specific flow string from this workbook.

### What each observation proves

| Evidence | What it tells you | What it does not prove |
| --- | --- | --- |
| NB logical port row | OVN's desired logical attachment exists | A VM or host interface exists |
| SB Port_Binding | OVN's control plane knows about a binding | Guest IP configuration or end-to-end reachability |
| OVS Interface with `iface-id` | A local OVS interface claims that logical port | That the guest application is healthy |
| OVS flow table | Rules are installed in the local switch | That the physical network beyond this host is correct |
| Successful `ovn-trace` | The simulated packet is accepted by the logical pipeline | That a real packet traversed the system |

### Optional instructor demonstration: attach a VM interface

This is an instructor-led demonstration only. Do not run it unless the
instructor has supplied a real host interface name and confirmed that it is
safe to attach. An interface name is not interchangeable with a logical port
name. The hypervisor or VM manager normally performs the attachment and sets
the appropriate OVS external ID. Attaching the wrong interface or editing
`br-int` manually can disconnect a workload.

### Questions

1. Which database is the source of desired logical configuration?
2. Which component on a chassis reports its local attachment state?
3. Why is a Port_Binding row not the same thing as a successful ping?

---

## Module 9: Become Fluent in `ovn-trace`

### Learning goal

Construct microflows methodically and explain why a trace can take a different
path when one packet field changes.

### A trace is a "what if?"

`ovn-trace` simulates a packet in OVN's logical pipeline. It needs a starting
datapath and enough packet fields to determine the matching rules. For a
useful IPv4 Layer 2/Layer 3 trace, specify at least:

* `inport`: the logical switch port where the packet enters;
* `eth.src` and `eth.dst`: Ethernet source and destination;
* `ip4.src` and `ip4.dst`: IPv4 source and destination;
* protocol fields when relevant, such as `icmp4.type`, `tcp.dst`, or
  `udp.dst`.

The shell quoting around the microflow keeps its `&&` operators and spaces
together as one argument. In a shell that uses different quoting rules,
adapt the quotes without changing the microflow itself.

### Exercise: compare three packets

Use the routed topology from Module 3. Run one trace at a time and note the
final action.

**A. Same-subnet Ethernet delivery**

```bash
ovn-trace --summary sw-tenant1 'inport == "port-vm-a" && eth.src == 50:54:00:00:00:0A && eth.dst == 50:54:00:00:00:0B && ip4.src == 10.0.1.10 && ip4.dst == 10.0.1.20'
```

Both addresses are in `10.0.1.0/24`, so VM-A can send an Ethernet frame
directly toward VM-B. In the simulator, no logical router is needed for this
same-subnet delivery.

**B. Off-subnet delivery through the logical router**

```bash
ovn-trace --summary sw-tenant1 'inport == "port-vm-a" && eth.src == 50:54:00:00:00:0A && eth.dst == 00:00:00:00:01:FF && ip4.src == 10.0.1.10 && ip4.dst == 10.0.2.10 && ip.ttl == 64'
```

The destination IP is outside `10.0.1.0/24`, so the guest sends the Ethernet
frame to its gateway MAC. The IP destination remains VM-C. Routers forward
using IP addresses and replace the link-layer header for the next hop.

**C. The same packet with an unusable TTL**

```bash
ovn-trace --summary sw-tenant1 'inport == "port-vm-a" && eth.src == 50:54:00:00:00:0A && eth.dst == 00:00:00:00:01:FF && ip4.src == 10.0.1.10 && ip4.dst == 10.0.2.10 && ip.ttl == 1'
```

Predict the outcome before running it. Compare the router stage with trace B.

### A repeatable debugging method

When a trace does not match your expectation:

1. Confirm the named logical port exists: `ovn-nbctl show`.
2. Confirm the datapath is the switch where `inport` belongs.
3. Check spelling and case of the port, IP, and MAC values.
4. Add enough fields to describe the packet and the protocol under test.
5. Check port security, routes, ACLs, NAT, and the port's logical type.
6. Read the trace from ingress to its final action; do not inspect only the
   last line.
7. If the logical trace succeeds but real traffic fails, move to SB binding,
   guest configuration, local OVS, tunnel, and physical-network checks.

### Questions

1. In trace B, why is the Ethernet destination a gateway MAC while the IP
   destination is still VM-C?
2. Does `ovn-trace` send an ICMP echo request to VM-C?
3. What additional data would you add to trace a TCP connection to port 443?

---

## Module 10: Observe a Physical Network Path and Its Limits

### Learning goal

Separate the OVN logical description of an external network from the OVS
bridge mapping and physical network that make external traffic possible.

### The idea

A `localnet` logical switch port represents a connection between an OVN
logical switch and a physical network. The `network_name=physnet1` option is
a label. On each relevant chassis, the OVN controller must be told how that
label maps to a local OVS bridge, and the bridge must reach the correct
physical VLAN/network. The logical port alone creates neither the mapping
nor the external router.

### Exercise: build an evidence checklist

Do not change host networking in this exercise. Use the NB and SB views, and
ask the instructor to demonstrate the chassis configuration if it is
available.

**Step 1. Inspect the logical localnet port.**

```bash
ovn-nbctl find Logical_Switch_Port name=ln-ext
ovn-nbctl get Logical_Switch_Port ln-ext type
ovn-nbctl get Logical_Switch_Port ln-ext options
```

Confirm that the type is `localnet` and the option contains
`network_name=physnet1`.

**Step 2. Inspect the router's external interface and route.**

```bash
ovn-nbctl list Logical_Router_Port
ovn-nbctl lr-route-list router-tenant
ovn-nbctl lr-nat-list router-tenant
```

Identify the router port with `172.16.1.1/24`, the default route through
`172.16.1.254`, and the SNAT row. If a command is unavailable in your OVN
release, use `ovn-nbctl --help` or the installed man page to find that
release's supported inspection command.

**Step 3. Inspect chassis and local bridge evidence.**

On the OVN database client:

```bash
ovn-sbctl show
```

On each relevant chassis, read-only:

```bash
ovs-vsctl show
ovs-vsctl get Open_vSwitch . external_ids:ovn-bridge-mappings
```

The mapping should connect the physnet name to the intended bridge, for
example `physnet1:br-ex`. A name in the mapping is not enough: the bridge
must have the correct uplink/VLAN and the upstream router must have a return
path for translated traffic.

**Step 4. Draw two paths.**

For VM-A to an external IP, draw:

1. the **logical path**: VM-A port -> logical switch -> logical router ->
   route/NAT -> localnet port; and
2. the **physical path**: chassis OVS -> mapped bridge/uplink -> physical
   network -> upstream router.

Label every item in your drawing with the command/database that provides
evidence for it.

### Questions

1. Which part of the path is described by `network_name=physnet1`?
2. Which chassis-side configuration connects that name to a bridge?
3. What route must exist for replies to return to the OVN network?
4. Why can `ovn-trace` show an external output even when the external cable
   is unplugged?

---

## Module 11: Compare ACL Direction, Priority, and Stateful Actions

### Learning goal

Explore the difference between allowing, rejecting, and dropping packets,
and understand that the ACL direction determines which port the rule protects.

### The idea

An ACL decision depends on its stage, priority, match expression, and action.
`drop` discards a matching packet. `reject` discards it and requests an
appropriate rejection response when possible. `allow` permits a packet;
`allow-related` also handles related connection-tracking traffic. Exact
details depend on protocol and OVN version.

The existing Module 4 policy protects traffic delivered to VM-C (`to-lport`).
An `from-lport` policy applies to packets entering the logical switch from
the named ingress port. Do not mix up inbound traffic to a VM with traffic
originating at that VM.

### Exercise: protect VM-A's egress

This exercise adds an egress policy on `sw-tenant1`. It permits DNS queries
over UDP to destination port 53 from VM-A and drops other UDP packets from
that port. Use a disposable lab: ACLs affect real traffic if ports are
connected to guests.

**Step 1. Add a specific allow at a higher priority.**

```bash
ovn-nbctl acl-add sw-tenant1 from-lport 2000 \
  'inport == "port-vm-a" && udp.dst == 53' allow-related
```

Read the match in parts: this is traffic **from** a logical switch port; the
port must be VM-A; and the packet must be UDP with destination port 53.

**Step 2. Add a lower-priority UDP drop for VM-A.**

```bash
ovn-nbctl acl-add sw-tenant1 from-lport 1000 \
  'inport == "port-vm-a" && udp' drop
```

Specific allowed DNS traffic matches the priority-2000 rule first. Other UDP
traffic from VM-A matches priority 1000 and is dropped.

**Step 3. Inspect the ACLs.**

```bash
ovn-nbctl acl-list sw-tenant1
```

Check the direction, priority, match, and action for both rows.

**Step 4. Trace UDP to two destinations.**

Use an off-subnet packet so it attempts to route, and compare DNS with UDP
port 12345:

```bash
ovn-trace --summary sw-tenant1 'inport == "port-vm-a" && eth.src == 50:54:00:00:00:0A && eth.dst == 00:00:00:00:01:FF && ip4.src == 10.0.1.10 && ip4.dst == 8.8.8.8 && udp.dst == 53 && udp.src == 53000 && ip.ttl == 64'
ovn-trace --summary sw-tenant1 'inport == "port-vm-a" && eth.src == 50:54:00:00:00:0A && eth.dst == 00:00:00:00:01:FF && ip4.src == 10.0.1.10 && ip4.dst == 8.8.8.8 && udp.dst == 12345 && udp.src == 53000 && ip.ttl == 64'
```

If the DNS trace does not pass, inspect all other ACLs and policies on the
switch; another rule may be taking precedence. Do not infer behavior from
these two rows alone when working in a pre-populated deployment.

### Questions

1. Why is the allow rule at a numerically higher priority?
2. What would change if you used `to-lport` instead of `from-lport`?
3. Does this policy allow DNS replies to return? Explain what stateful action
   and related traffic mean for the test.

---

## Module 12: Publish One Tenant Address with DNAT and SNAT

### Learning goal

Compare outbound SNAT with inbound destination translation and identify the
requirements for a usable floating/public address.

### The idea

* **SNAT** changes a packet's source address as it leaves a private network.
* **DNAT** changes a packet's destination address as it enters a private
  network.
* A **floating IP** commonly maps an external address to a tenant address.
  In OVN, `dnat_and_snat` combines inbound destination translation with
  source translation for the corresponding traffic.

NAT is not a physical firewall rule and does not create external reachability
by itself. The external logical network, route, chassis mapping, upstream
network, and security policy must all be appropriate.

### Exercise: map an example external address to VM-C

Use `172.16.1.20` only if it is reserved for your isolated lab. Do not use an
address already assigned to another device.

**Step 1. Add a combined NAT mapping.**

```bash
ovn-nbctl lr-nat-add router-tenant dnat_and_snat 172.16.1.20 10.0.2.10
```

The command associates the external address `172.16.1.20` with VM-C's
internal address `10.0.2.10` on `router-tenant`.

**Step 2. Verify the router's NAT configuration.**

```bash
ovn-nbctl lr-nat-list router-tenant
```

Confirm the type and both addresses. The external address must belong to a
reachable external network and must not conflict with the existing router
address `172.16.1.1`.

**Step 3. Trace from the external logical switch.**

```bash
ovn-trace --summary external-network 'inport == "ln-ext" && eth.src == 02:00:00:00:01:FE && eth.dst == 00:01:20:20:12:13 && ip4.src == 172.16.1.254 && ip4.dst == 172.16.1.20 && tcp.dst == 80 && tcp.src == 50000 && ip.ttl == 64'
```

The trace models a packet from an upstream neighbor entering through the
localnet logical port and addressed to the external mapping. Follow it as it
crosses the router and is directed toward `10.0.2.10`. The example source MAC
is illustrative: use the actual upstream router MAC if your lab requires it.

**Step 4. Explain the missing requirements.**

Even if the logical trace is as expected, ask what else must be true:

* An upstream route or neighbor behavior must deliver traffic for
  `172.16.1.20` to the OVN external network.
* A chassis must bind the localnet network to the physical bridge.
* An ACL must permit the intended traffic to VM-C.
* VM-C must be connected, configured, and listening on TCP port 80.
* Return traffic must follow a path that preserves the NAT connection state.

### Questions

1. Which address does the external client target?
2. Which address should VM-C see after destination translation?
3. Why is a successful trace not a complete test of a floating IP?

---

## Module 13: Read the OVN Topology Viewer

### Learning goal

Use a diagram as a second representation of database state, then verify
important conclusions with the native OVN commands.

### The idea

The project in this repository can query OVN and present the topology using
Graphviz or Mermaid. The diagram is a convenience view of the state it reads;
it does not replace checking the NB database, SB bindings, local OVS, or a
packet trace. Mermaid mode renders in the browser and needs access to the
configured Mermaid CDN. Graphviz mode needs the `dot` executable on the
viewer host.

### Exercise: run the viewer in Mermaid mode

From the project root, install the application and its Python dependencies:

```bash
python3 -m pip install -e .
```

The project requires Python 3.10 or newer. If OVN commands are available
directly on the machine, run:

```bash
python3 ovn_topology.py --container "" --renderer mermaid --port 8080
```

If the OVN tools are in a container, use the container name provided by the
instructor instead of an empty `--container` value:

```bash
python3 ovn_topology.py --container ovn-central-az1 --renderer mermaid --port 8080
```

Open <http://localhost:8080> in a browser. Select or view the topology and
compare its switches, routers, ports, provider networks, and chassis with:

```bash
ovn-nbctl show
ovn-sbctl show
```

For Graphviz, select the other launch mode:

```bash
python3 ovn_topology.py --container "" --renderer graphviz --port 8080
```

### Student task

Choose one object in the diagram. Find the same object in the correct OVN
database and write down its name and relevant fields. Then choose one apparent
connection in the diagram and identify the command or database row that
confirms it. A visual edge may simplify details; do not treat the picture as
proof that a live guest or physical link is working.

---

## Module 14: Troubleshooting Practicum

For each scenario, first say which layer you will check and why. Then run the
read-only commands and compare their evidence. Do not change a shared
deployment while diagnosing.

### Scenario A: "I created the port, but the VM cannot communicate."

Check:

```bash
ovn-nbctl show
ovn-sbctl --columns=logical_port,type,chassis,datapath list Port_Binding
```

On the assigned chassis, check:

```bash
ovs-vsctl show
ovs-vsctl --columns=name,ofport,external_ids list Interface
```

Then confirm the guest's interface address, subnet, and default gateway. A
logical port in NB is only the first piece of evidence.

### Scenario B: "A same-subnet trace drops."

Check the ingress port's port-security addresses and the microflow's source
MAC/IP. Confirm that the destination port is on the same switch and that no
ACL blocks it:

```bash
ovn-nbctl get Logical_Switch_Port port-vm-a port_security
ovn-nbctl get Logical_Switch_Port port-vm-b addresses
ovn-nbctl acl-list sw-tenant1
```

Change exactly one field in the trace at a time so you can identify the
condition that changes the result.

### Scenario C: "Routing to another subnet fails."

Check that the two router ports have addresses in the correct subnets and
that each switch's router-type logical port references the matching router
port:

```bash
ovn-nbctl show
ovn-nbctl list Logical_Router_Port
ovn-nbctl lr-route-list router-tenant
```

Also check that the simulated Ethernet destination is the gateway MAC and
that the IP destination remains the remote guest's IP. For real traffic,
check the guest's default route too.

### Scenario D: "`ovn-trace` succeeds, but external ping fails."

Treat this as a transition from logical debugging to physical debugging.
Check the localnet `network_name`, chassis bridge mapping, OVS bridge/uplink,
VLAN, upstream route, security policy, and return path. Then capture packets
at the appropriate guest and physical interfaces using the tools approved
for the lab. A successful logical trace does not test those components.

### Scenario E: "The topology viewer has no chassis port placement."

Compare SB Port_Binding and the chassis list. If a VM interface is expected,
check on the host that it is attached to OVS and has the expected
`iface-id`. A topology diagram cannot infer a physical binding that is absent
from the database.

### Reporting template

For each issue, write:

1. **Symptom:** What exactly failed?
2. **Layer:** Guest, logical NB state, SB binding, local OVS, tunnel, or
   physical network?
3. **Evidence:** Which command output supports that layer?
4. **Hypothesis:** What is the most likely cause?
5. **Next test:** What single read-only check would confirm or reject it?
6. **Fix and verification:** What change is approved, and what observation
   proves the problem is resolved?

---

## Final Review and Instructor Discussion

Without looking back, explain the packet path in this example:

```text
VM-A (10.0.1.10)
  -> sw-tenant1
  -> router-tenant (10.0.1.1 / 10.0.2.1)
  -> sw-tenant2
  -> VM-C (10.0.2.10)
```

Then answer:

1. Which component stores the logical intent?
2. Which service translates NB state for chassis?
3. Which agent programs local OVS?
4. What does `ovn-trace` simulate, and what does it not prove?
5. What is the difference between a logical port and an OVS interface?
6. Why does Internet access need more than an SNAT row?
7. Which evidence would you collect before concluding that a real VM is
   attached to the correct chassis?

### Instructor answer guide

1. The NB database stores logical intent.
2. `ovn-northd` translates NB configuration into SB state.
3. `ovn-controller` on each chassis programs the local OVS instance.
4. `ovn-trace` simulates a packet through OVN's logical pipeline; it does not
   send a packet or validate guest, tunnel, uplink, or remote-router health.
5. A logical port is OVN's desired attachment; an OVS interface is a host's
   actual interface. A VM manager connects the two and supplies the logical
   port identity.
6. External access also depends on routes, physical-network mapping, VLAN and
   uplink configuration, upstream forwarding and return routing, and any
   ACL/firewall policy.
7. Correlate the NB logical port, SB Port_Binding chassis, OVS Interface
   `iface-id`, and the guest's interface/configuration. No single one of
   these observations proves the entire end-to-end path.

---

## Lab Cleanup

Only clean up objects you created in the disposable classroom database.
Before deleting anything, inspect the current state and confirm that the
names are not used by another student or service.

The following commands remove the example routers and switches used in this
workbook. Deleting a router or switch removes the logical object and can
remove associated logical ports; it does not delete VMs or configure host
OVS. Use them only when the instructor confirms the lab is disposable:

```bash
ovn-nbctl lr-del router-tenant
ovn-nbctl ls-del sw-tenant1
ovn-nbctl ls-del sw-tenant2
ovn-nbctl ls-del external-network
ovn-nbctl ls-del sw-dhcp
```

If a logical switch or router has already been deleted, the corresponding
command may report that it does not exist. Do not broaden cleanup to all
logical switches, routers, chassis, or OVS bridges.

## Further Reading

Use the man pages installed with your OVN/OVS release as the authority for
exact command options and supported match fields:

* [`ovn-nbctl(8)`](https://www.ovn.org/support/dist-docs/ovn-nbctl.8.html)
* [`ovn-sbctl(8)`](https://www.ovn.org/support/dist-docs/ovn-sbctl.8.html)
* [`ovn-trace(8)`](https://www.ovn.org/support/dist-docs/ovn-trace.8.html)
* [`ovn-architecture(7)`](https://www.ovn.org/support/dist-docs/ovn-architecture.7.html)
* [Open vSwitch documentation](https://docs.openvswitch.org/en/latest/)

The online documentation may describe a newer release than your classroom
environment. Always compare examples with the version reported by your own
commands.
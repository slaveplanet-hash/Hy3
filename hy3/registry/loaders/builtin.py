"""Builtin capability seeds.

These are the hand-authored, always-available capabilities derived directly from
the HY3 build plan:

  * planner meta-caps + the pinned set (plan §5)            -> plan.*, memory.search, report.write
  * network + PC read/write/destructive tier (plan §9)      -> net.*, pc.*
  * deep-research pipeline (plan §11)                       -> research.*, web.*, rag.search
  * desktop control primitives (plan §10)                  -> desktop.*
  * the local model brain (plan §6)                        -> model.*
  * skill learning lifecycle (plan §12)                    -> skill.*

In Phase 1 these are *declarations* — the schema the planner sees. Their ``handler``
is a no-op until the execution phase wires it; that is intentional. Routing and the
console work against the schema alone.

net.* capabilities carry ``requires=("netscope_server",)`` so the precondition gate
can emit the real "start node server.js, open http://localhost:8089/" message once,
instead of every caller re-deriving it (plan §9.1).
"""
from __future__ import annotations

from ..capability import Capability, Cost, Kind, Risk

# (id, kind, summary, risk, tags, requires)
_SEED: tuple[tuple[str, str, str, str, tuple[str, ...], tuple[str, ...]], ...] = (
    # --- planner meta / pinned set -----------------------------------------
    ("plan.replan", "tool", "Re-plan the goal when a job fails or the DAG needs reformulation.", "read",
     ("planning", "replan", "orchestration", "dag"), ()),
    ("memory.search", "retriever", "Retrieve relevant episodic and semantic memory for a sub-goal.", "read",
     ("memory", "retrieve", "episodic", "semantic", "recall"), ()),
    ("report.write", "tool", "Write the final synthesized report artifact for a session.", "write",
     ("report", "synthesis", "output", "artifact"), ()),

    # --- network tier (plan §9) --------------------------------------------
    ("net.scan.lan", "tool", "Discover hosts on the LAN via ping sweep, ARP, and port probes.", "read",
     ("network", "scan", "discovery", "lan", "hosts", "arp"), ("netscope_server",)),
    ("net.config.get", "tool", "Read network configuration: adapters, IPs, DNS, and routes.", "read",
     ("network", "config", "ipconfig", "dns", "routes"), ("netscope_server",)),
    ("net.hosts.list", "tool", "List discovered hosts with vendor OUI and open ports.", "read",
     ("network", "hosts", "discovery", "oui", "ports"), ("netscope_server",)),
    ("net.conn.list", "tool", "List active network connections with process ownership.", "read",
     ("network", "connections", "netstat", "flows"), ("netscope_server",)),
    ("net.l7.flows", "tool", "Show layer-7 flows: process-to-domain mapping and DNS cache.", "read",
     ("network", "l7", "flows", "dns", "process"), ("netscope_server",)),
    ("net.ports.listening", "tool", "List local listening ports mapped to owning processes.", "read",
     ("network", "ports", "listening", "process"), ("netscope_server",)),
    ("net.endpoint.whois", "tool", "Reverse-DNS and RDAP owner lookup for a remote endpoint.", "read",
     ("network", "whois", "rdap", "endpoint", "owner"), ("netscope_server",)),
    ("net.report.export", "tool", "Export a markdown AI report bundling scan findings.", "read",
     ("network", "report", "export", "markdown"), ("netscope_server",)),
    ("net.diag.dns", "tool", "Diagnose DNS resolution and validate DNSSEC for a name.", "read",
     ("network", "dns", "diagnose", "dnssec", "resolve"), ("netscope_server",)),
    ("net.diag.traceroute", "tool", "Traceroute to a target with per-hop RTT.", "read",
     ("network", "traceroute", "diagnose", "rtt", "hops"), ("netscope_server",)),
    ("net.diag.tls", "tool", "Inspect a TLS certificate chain for a host:port.", "read",
     ("network", "tls", "certificate", "diagnose", "ssl"), ("netscope_server",)),
    ("net.throughput.test", "tool", "Measure throughput to a target over TCP/HTTP.", "read",
     ("network", "throughput", "performance", "speed", "test"), ("netscope_server",)),
    ("net.baseline.capture", "tool", "Snapshot hosts, ports, services, and config as a baseline artifact.", "read",
     ("network", "pc", "baseline", "snapshot", "drift"), ()),
    ("net.baseline.diff", "tool", "Diff current state against the last known-good baseline.", "read",
     ("network", "pc", "baseline", "diff", "drift", "change"), ()),
    ("net.firewall.rule", "tool", "Add or remove a Windows firewall rule (snapshot-first).", "write",
     ("network", "firewall", "rule", "write"), ()),
    ("net.config.dns.set", "tool", "Change the system DNS resolver (snapshot-first).", "write",
     ("network", "dns", "config", "write", "resolver"), ()),
    ("net.adapter.powermgmt", "tool", "Toggle adapter power management (the Wi-Fi drop fix).", "write",
     ("network", "wifi", "adapter", "power", "write", "fix"), ()),

    # --- PC tier (plan §9.2/9.3/9.6) ---------------------------------------
    ("pc.host.info", "tool", "Collect local Windows host info: OS, hardware, users, uptime.", "read",
     ("pc", "host", "systeminfo", "inventory"), ()),
    ("pc.svc.list", "tool", "List Windows services with state and startup type.", "read",
     ("pc", "services", "list", "inventory"), ()),
    ("pc.svc.restart", "tool", "Start, stop, or restart a Windows service (snapshot-first).", "write",
     ("pc", "services", "restart", "write"), ()),
    ("pc.disk.smart", "tool", "Read SMART health attributes for local disks.", "read",
     ("pc", "disk", "smart", "health"), ()),
    ("pc.scheduled.list", "tool", "List scheduled tasks on the host.", "read",
     ("pc", "scheduled", "tasks", "list"), ()),
    ("pc.firewall.list", "tool", "List active Windows firewall rules.", "read",
     ("pc", "firewall", "list", "rules"), ()),

    # --- memory / retrieval ------------------------------------------------
    ("memory.flag_bad", "tool", "Flag a memory as incorrect for operator review.", "write",
     ("memory", "flag", "poisoning", "review"), ()),

    # --- deep research (plan §11) ------------------------------------------
    ("rag.search", "retriever", "Retrieve chunks from local RAG corpora (Network MD, docs).", "read",
     ("rag", "retrieve", "corpus", "documents", "research"), ()),
    ("web.search", "retriever", "Search the web via SearXNG and return JSON results.", "read",
     ("web", "search", "searxng", "research"), ()),
    ("web.fetch", "tool", "Fetch and extract readable text from a URL.", "read",
     ("web", "fetch", "scrape", "research"), ()),
    ("research.decompose", "tool", "Decompose a research question into sub-questions.", "read",
     ("research", "decompose", "planning", "questions"), ()),
    ("research.synthesize", "tool", "Synthesize extracted claims into a cited report.", "read",
     ("research", "synthesize", "report", "citations"), ()),

    # --- desktop control (plan §10) ----------------------------------------
    ("desktop.read_ui_tree", "tool", "Read the Windows UI Automation control tree.", "read",
     ("desktop", "uiautomation", "tree", "perception"), ()),
    ("desktop.screenshot", "tool", "Capture a screenshot of the desktop.", "read",
     ("desktop", "screenshot", "vision", "perception"), ()),
    ("desktop.click", "tool", "Click a UI element by target id (write tier).", "write",
     ("desktop", "click", "action", "write"), ()),
    ("desktop.type_text", "tool", "Type text into the focused control (write tier).", "write",
     ("desktop", "type", "action", "write"), ()),
    ("desktop.launch", "tool", "Launch an allowlisted application alias (write tier).", "write",
     ("desktop", "launch", "action", "allowlist", "write"), ()),

    # --- local model brain (plan §6) ---------------------------------------
    ("model.plan", "model", "Run the local boss model to produce a plan or DAG.", "read",
     ("model", "planning", "boss", "llm"), ()),
    ("model.complete", "model", "Run a local model to completion with a schema or grammar.", "read",
     ("model", "completion", "llm", "schema", "grammar"), ()),

    # --- skill learning lifecycle (plan §12) ------------------------------
    ("skill.propose", "tool", "Propose a new skill from successful job traces.", "write",
     ("skill", "propose", "learning"), ()),
    ("skill.promote", "tool", "Promote a reviewed skill into the registry (privileged).", "privileged",
     ("skill", "promote", "learning", "registry"), ()),
)


def load() -> list[Capability]:
    """Return the full set of builtin capabilities."""
    return [
        Capability.build(
            id=cid,
            kind=kind,
            summary=summary,
            risk=risk,
            tags=tags,
            requires=requires,
            provenance="builtin",
        )
        for (cid, kind, summary, risk, tags, requires) in _SEED
    ]

// Mock device data shaped to the real MonCTL `Device` schema.
// 2000 devices, deterministic via a seeded RNG.

(function () {
  function rng(seed) {
    return function () {
      seed = (seed * 1664525 + 1013904223) >>> 0;
      return seed / 4294967296;
    };
  }

  const CATEGORIES = [
    { name: "cisco-router",   icon: "router",   types: ["Cisco ASR 1002-X", "Cisco ISR4331/K9", "Cisco C8231-E-G2", "Cisco C8300 1N1S6T"] },
    { name: "cisco-switch",   icon: "switch",   types: ["Cisco WS-C4506-E", "Cisco C8500L-8S4X", "Cisco Catalyst 9200", "Cisco NCS 55A2MODS"] },
    { name: "juniper-switch", icon: "switch",   types: ["Juniper EX3300-48p", "Juniper EX4300-32F", "Juniper QFX5120-48Y"] },
    { name: "juniper-router", icon: "router",   types: ["Juniper MX204", "Juniper MX480"] },
    { name: "linux-server",   icon: "server",   types: ["Linux (net-snmp)", "Ubuntu 22.04", "Debian 12"] },
    { name: "docker_host",    icon: "container",types: [null] },
    { name: "f5-bigip",       icon: "shield",   types: ["F5 BIG-IP i4800", "F5 BIG-IP i7800"] },
    { name: "palo-firewall",  icon: "firewall", types: ["PA-3260", "PA-5250"] },
  ];

  const TENANTS = ["Test network", "Production", "Staging", "DC-North", "DC-South", "Edge-EU"];
  const GROUPS  = ["Network devices", "Web", "Compute", "Edge", "Core", "DMZ"];
  const SITES   = ["test01", "test02", "prod01", "prod02", "edge01", "dc-n01", "dc-s01"];
  const ROLES   = ["acc", "oh", "or", "ow", "pu", "sw", "co"];

  const pad = (n, w) => String(n).padStart(w, "0");

  function ts(r, daysSpread) {
    const d = new Date(2026, 2, 12, 9, 24, 59);
    d.setDate(d.getDate() + Math.floor(r() * daysSpread));
    d.setHours(Math.floor(r() * 24), Math.floor(r() * 60), Math.floor(r() * 60));
    const f = (n) => String(n).padStart(2, "0");
    return `${d.getFullYear()}-${f(d.getMonth()+1)}-${f(d.getDate())} ${f(d.getHours())}:${f(d.getMinutes())}:${f(d.getSeconds())}`;
  }

  function gen(count) {
    const r = rng(424242);
    const list = [];
    for (let i = 0; i < count; i++) {
      const cat = CATEGORIES[Math.floor(r() * CATEGORIES.length)];
      const type = cat.types[Math.floor(r() * cat.types.length)];
      const isCol = i < 6;
      const name = isCol
        ? `collector-${pad(i+1, 2)}`
        : `${SITES[Math.floor(r() * SITES.length)]}${ROLES[Math.floor(r() * ROLES.length)]}${pad(Math.floor(r()*99)+1,2)}.ip.norlys.io`;
      const addr = `10.${145 + Math.floor(r()*4)}.${200 + Math.floor(r()*55)}.${1 + Math.floor(r()*254)}`;
      const rr = r();
      const reachable = rr < 0.78 ? true : rr < 0.94 ? false : null; // null = unknown
      const enabled = r() > 0.04;
      const rtt = reachable ? +(2 + r() * 30).toFixed(1) : null;
      const alerts = reachable === false ? Math.floor(r()*4)+1
                  : reachable === null ? 0
                  : r() < 0.1 ? 1 : 0;
      const labels = [];
      if (r() < 0.5) labels.push({ key: "env", value: ["prod","stage","dev"][Math.floor(r()*3)], color: "blue" });
      if (r() < 0.3) labels.push({ key: "team", value: ["net","ops","sec"][Math.floor(r()*3)], color: "purple" });
      // 60-tick heartbeat
      const hb = [];
      for (let k=0;k<60;k++) {
        const drop = reachable === false ? 0.85 : reachable === null ? 0.5 : 0.02;
        hb.push(r() > drop ? 1 : 0);
      }
      list.push({
        id: `dev_${i}`,
        name, address: addr,
        device_category: cat.name,
        category_icon: cat.icon,
        device_type_name: type,
        tenant_name: TENANTS[Math.floor(r()*TENANTS.length)],
        collector_group_name: GROUPS[Math.floor(r()*GROUPS.length)],
        labels,
        is_enabled: enabled,
        reachable,
        rtt_ms: rtt,
        alerts,
        heartbeat: hb,
        last_poll_sec: reachable === false ? Math.floor(r()*3600)+300 : Math.floor(r()*60)+1,
        created_at: ts(r, 50),
        updated_at: ts(r, 50),
      });
    }
    return list;
  }

  const ALL = gen(2000);

  function counts(list) {
    const c = { up: 0, down: 0, unknown: 0, disabled: 0 };
    for (const d of list) {
      if (!d.is_enabled) c.disabled++;
      else if (d.reachable === true) c.up++;
      else if (d.reachable === false) c.down++;
      else c.unknown++;
    }
    return c;
  }

  function fmtRel(s) {
    if (s < 60) return `${s}s ago`;
    if (s < 3600) return `${Math.floor(s/60)}m ago`;
    if (s < 86400) return `${Math.floor(s/3600)}h ago`;
    return `${Math.floor(s/86400)}d ago`;
  }

  window.MONCTL = { ALL, TENANTS, GROUPS, CATEGORIES, counts, fmtRel };
})();

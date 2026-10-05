const $ = id => document.getElementById(id);
  const KINDS = ['router', 'switch', 'port', 'provider', 'chassis'];
  let current = -1, pz = null, idx = null;

  // ---------------- filter state (persisted) ----------------
  function loadF() { try { return JSON.parse(localStorage.getItem('ovn-filter') || '{}'); } catch (e) { return {}; } }
  function saveF() { try { localStorage.setItem('ovn-filter', JSON.stringify(F)); } catch (e) {} }
  const F = Object.assign({ q: '', kinds: {}, status: 'all', hops: 1, mode: 'dim' }, loadF());

  function syncUI() {
    $('q').value = F.q;
    document.querySelectorAll('#toolbar input[data-kind]').forEach(cb => cb.checked = F.kinds[cb.dataset.kind] !== false);
    $('status-f').value = F.status; $('hops').value = String(F.hops); $('mode').value = F.mode;
  }

  // ---------------- SVG index ----------------
  // Node type/status are derived from the node id and text, so this also works with
  // Graphviz versions that do not emit custom CSS classes.
  const PREFIX = { router_: 'router', switch_: 'switch', port_: 'port', provider_: 'provider', chassis_: 'chassis' };
  function kindOf(el, id) {
    const k = KINDS.find(k => el.classList.contains(k));
    if (k) return k;
    for (const p in PREFIX) if (id.startsWith(p)) return PREFIX[p];
    return 'other';
  }
  function statusOf(el, text) {
    if (el.classList.contains('up')) return 'up';
    if (el.classList.contains('down') || el.classList.contains('disabled')) return 'down';
    if (el.querySelector('text[fill="#22c55e"]')) return 'up';
    if (el.querySelector('text[fill="#ef4444"]') || el.querySelector('text[fill="#a1a1aa"]')) return 'down';
    return '';
  }
  let clientErr = '';
  function showErr(msg) { clientErr = msg; console.error(msg); }

  function buildIndex() {
    const svg = $('diagram').querySelector('svg');
    if (!svg) { idx = null; return; }
    const title = g => (g.querySelector('title') || {}).textContent || '';
    const nodes = [...svg.querySelectorAll('g.node')].map(el => {
      const id = title(el).trim();
      const text = el.textContent.toLowerCase().replace(/\s+/g, ' ');
      return { el, id, kind: kindOf(el, id), status: statusOf(el, text), text, rect: el.getBoundingClientRect() };
    });
    const adj = new Map();
    const edges = [...svg.querySelectorAll('g.edge')].map(el => {
      const [a, b] = title(el).split('->').map(x => x.trim());
      if (!adj.has(a)) adj.set(a, new Set());
      if (!adj.has(b)) adj.set(b, new Set());
      adj.get(a).add(b); adj.get(b).add(a);
      return { el, a, b };
    });
    // Graphviz does not nest nodes inside cluster <g>, so map membership geometrically.
    const clusters = [...svg.querySelectorAll('g.cluster')].map(el => {
      const r = el.getBoundingClientRect();
      const ids = nodes.filter(n => {
        const cx = (n.rect.left + n.rect.right) / 2, cy = (n.rect.top + n.rect.bottom) / 2;
        return cx >= r.left && cx <= r.right && cy >= r.top && cy <= r.bottom;
      }).map(n => n.id);
      return { el, ids };
    });
    idx = { nodes, edges, clusters, adj };
  }

  // ---------------- filtering ----------------
  function apply() {
    if (!idx) return;
    const terms = F.q.toLowerCase().split(/\s+/).filter(Boolean);
    const kindOk = n => F.kinds[n.kind] !== false;
    const statusOk = n => n.kind !== 'port' || F.status === 'all' || n.status === F.status;
    const base = new Set(idx.nodes.filter(n => kindOk(n) && statusOk(n)).map(n => n.id));

    let visible, matched = new Set();
    if (terms.length) {
      matched = new Set(idx.nodes.filter(n => base.has(n.id) && terms.every(t => n.text.includes(t))).map(n => n.id));
      visible = new Set(matched);
      let frontier = [...matched];
      for (let h = 0; h < F.hops; h++) {            // expand context along links
        const next = [];
        for (const id of frontier) for (const nb of (idx.adj.get(id) || []))
          if (base.has(nb) && !visible.has(nb)) { visible.add(nb); next.push(nb); }
        frontier = next;
      }
      // keep the chassis box of any visible port, so you can see where it lives
      for (const c of idx.clusters) {
        if (!c.ids.some(id => visible.has(id))) continue;
        for (const n of idx.nodes) if (n.kind === 'chassis' && base.has(n.id) && c.ids.includes(n.id)) visible.add(n.id);
      }
    } else {
      visible = base;
    }

    const hide = F.mode === 'hide';
    const mark = (el, vis, isMatch) => {
      el.classList.toggle('dim', !vis && !hide);
      el.classList.toggle('gone', !vis && hide);
      el.classList.toggle('match', !!isMatch);
      el.style.opacity = (!vis && !hide) ? '0.1' : '';
      el.style.display = (!vis && hide) ? 'none' : '';
      el.style.filter = isMatch ? 'drop-shadow(0 0 6px #facc15)' : '';
    };
    idx.nodes.forEach(n => mark(n.el, visible.has(n.id), matched.has(n.id)));
    idx.edges.forEach(e => mark(e.el, visible.has(e.a) && visible.has(e.b), false));
    idx.clusters.forEach(c => mark(c.el, c.ids.some(id => visible.has(id)), false));
    $('count').textContent = visible.size + ' / ' + idx.nodes.length + ' items' + (terms.length ? ' (' + matched.size + ' matches)' : '');
  }

  function fitVisible() {
    if (!pz || !idx) return;
    const vis = idx.nodes.filter(n => !n.el.classList.contains('dim') && !n.el.classList.contains('gone'));
    if (!vis.length || vis.length === idx.nodes.length) { pz.resize(); pz.fit(); pz.center(); return; }
    const rs = vis.map(n => n.el.getBoundingClientRect());
    const L = Math.min(...rs.map(r => r.left)), R = Math.max(...rs.map(r => r.right));
    const T = Math.min(...rs.map(r => r.top)),  B = Math.max(...rs.map(r => r.bottom));
    const c = $('container').getBoundingClientRect();
    const px = c.left + c.width / 2, py = c.top + c.height / 2;     // zoom pivot = viewport centre
    const before = pz.getZoom();
    pz.zoom(before * Math.min(c.width / (R - L), c.height / (B - T)) * 0.85);
    const k = pz.getZoom() / before;
    const cx = px + k * ((L + R) / 2 - px), cy = py + k * ((T + B) / 2 - py);   // new centre of the matches
    pz.panBy({ x: px - cx, y: py - cy });
  }

  // ---------------- events ----------------
  let t = null;
  const onQ = e => { F.q = e.target.value; saveF(); clearTimeout(t); t = setTimeout(apply, 120); };
  ['input', 'search', 'change'].forEach(ev => $('q').addEventListener(ev, onQ));
  $('q').addEventListener('keydown', e => {
    if (e.key === 'Enter') fitVisible();
    if (e.key === 'Escape') { F.q = ''; $('q').value = ''; saveF(); apply(); $('q').blur(); }
  });
  document.addEventListener('keydown', e => {
    if (e.key === '/' && document.activeElement !== $('q')) { e.preventDefault(); $('q').focus(); }
  });
  document.querySelectorAll('#toolbar input[data-kind]').forEach(cb =>
    cb.addEventListener('change', () => { F.kinds[cb.dataset.kind] = cb.checked; saveF(); apply(); }));
  $('status-f').onchange = e => { F.status = e.target.value; saveF(); apply(); };
  $('hops').onchange = e => { F.hops = parseInt(e.target.value, 10); saveF(); apply(); };
  $('mode').onchange = e => { F.mode = e.target.value; saveF(); apply(); };
  $('fit').onclick = fitVisible;
  $('reset').onclick = () => {
    Object.assign(F, { q: '', kinds: {}, status: 'all', hops: 1, mode: 'dim' });
    saveF(); syncUI(); apply(); if (pz) { pz.resize(); pz.fit(); pz.center(); }
  };

  // ---------------- OVN trace ----------------
  let traceDatapaths = [], traceVersion = -1;
  function setSelect(id, placeholder, values, selectedValue, keepPlaceholder = false) {
    const select = $(id);
    select.replaceChildren(new Option(placeholder, ''));
    values.forEach(value => select.add(new Option(value.label, value.value)));
    if (values.some(value => value.value === selectedValue)) select.value = selectedValue;
    else if (keepPlaceholder && selectedValue === '') select.selectedIndex = 0;
    else if (values.length) select.selectedIndex = 1;
    select.disabled = values.length === 0;
  }
  function updateTraceFields() {
    const datapath = traceDatapaths.find(item => item.name === $('trace-datapath').value);
    if (!datapath) {
      setSelect('trace-inport', 'No datapath selected', [], '');
      setSelect('trace-src-mac', 'No MAC addresses available', [], '');
      setSelect('trace-dst-mac', 'No MAC addresses available', [], '');
      setSelect('trace-src-ip', 'No IP addresses available', [], '');
      setSelect('trace-dst-ip', 'No IP addresses available', [], '');
      $('trace-submit').disabled = true;
      refreshExtraTraceFields();
      return;
    }
    const portValue = $('trace-inport').value;
    const srcMacValue = $('trace-src-mac').value, dstMacValue = $('trace-dst-mac').value;
    const srcIpValue = $('trace-src-ip').value, dstIpValue = $('trace-dst-ip').value;
    setSelect('trace-inport', 'Choose ingress port', datapath.ports.map(port => ({
      label: port.name, value: port.name
    })), portValue);
    const macs = datapath.macs.map(mac => ({ label: mac, value: mac }));
    setSelect('trace-src-mac', 'Choose source MAC', macs, srcMacValue);
    setSelect('trace-dst-mac', 'Choose destination MAC', macs, dstMacValue || (macs[1] || {}).value);
    const ips = datapath.ips.map(ip => ({ label: ip, value: ip }));
    setSelect('trace-src-ip', 'No IP (L2 trace)', ips, srcIpValue, true);
    setSelect('trace-dst-ip', 'No IP (L2 trace)', ips, dstIpValue, true);
    $('trace-submit').disabled = !(datapath.ports.length && macs.length);
    refreshExtraTraceFields();
  }
  function traceFieldContext() {
    const fields = [...document.querySelectorAll('.trace-extra-row')];
    const valuesFor = name => fields
      .filter(row => row.querySelector('[data-trace-field]').value === name)
      .map(row => row.querySelector('[data-trace-value]').value.trim().toLowerCase());
    const selectedIps = [$('trace-src-ip').value, $('trace-dst-ip').value].filter(Boolean);
    const families = new Set(selectedIps.map(ip => ip.includes(':') ? 6 : 4));
    const ethTypes = valuesFor('eth.type');
    if (ethTypes.some(value => ['0x0800', '2048'].includes(value))) families.add(4);
    if (ethTypes.some(value => ['0x86dd', '34525'].includes(value))) families.add(6);
    const protocols = new Set(valuesFor('ip.proto').map(value => {
      const parsed = Number(value);
      return Number.isInteger(parsed) ? parsed : -1;
    }));
    return { fields, families, ethTypes, protocols };
  }
  function availableTraceFields(context, row) {
    const usedElsewhere = new Set(context.fields
      .filter(other => other !== row)
      .map(other => other.querySelector('[data-trace-field]').value)
      .filter(Boolean));
    const candidates = [
      ['eth.type', true],
      ['vlan.tci', true],
      ['ip4.src', context.families.has(4)],
      ['ip4.dst', context.families.has(4)],
      ['ip6.src', context.families.has(6)],
      ['ip6.dst', context.families.has(6)],
      ['ip.ttl', context.families.size > 0],
      ['ip.proto', context.families.size > 0],
      ['tcp.src', context.protocols.has(6)],
      ['tcp.dst', context.protocols.has(6)],
      ['udp.src', context.protocols.has(17)],
      ['udp.dst', context.protocols.has(17)],
      ['icmp4.type', context.families.has(4) && context.protocols.has(1)],
      ['icmp4.code', context.families.has(4) && context.protocols.has(1)],
      ['icmp6.type', context.families.has(6) && context.protocols.has(58)],
      ['icmp6.code', context.families.has(6) && context.protocols.has(58)],
      ['arp.op', context.ethTypes.some(value => ['0x0806', '2054'].includes(value))]
    ];
    return candidates.filter(([name, enabled]) => enabled && (!usedElsewhere.has(name) || row.querySelector('[data-trace-field]').value === name))
      .map(([name]) => name);
  }
  function updateExtraFieldSuggestions(row) {
    const datapath = traceDatapaths.find(item => item.name === $('trace-datapath').value);
    const field = row.querySelector('[data-trace-field]').value.trim();
    const values = !datapath ? [] :
      field === 'inport' ? datapath.ports.map(port => port.name) :
      field === 'eth.src' || field === 'eth.dst' ? datapath.macs :
      field === 'ip4.src' || field === 'ip4.dst' ? datapath.ips.filter(ip => !ip.includes(':')) :
      field === 'ip6.src' || field === 'ip6.dst' ? datapath.ips.filter(ip => ip.includes(':')) :
      [];
    const datalist = row.querySelector('datalist');
    datalist.replaceChildren(...values.map(value => {
      const option = document.createElement('option');
      option.value = value;
      return option;
    }));
    const examples = {
      'eth.type': '0x0800',
      'vlan.tci': '0x1000',
      'ip4.src': '192.0.2.1', 'ip4.dst': '192.0.2.2',
      'ip6.src': '2001:db8::1', 'ip6.dst': '2001:db8::2',
      'ip.ttl': '64',
      'ip.proto': '6',
      'tcp.src': '443', 'tcp.dst': '443',
      'udp.src': '53', 'udp.dst': '53',
      'icmp4.type': '8', 'icmp4.code': '0',
      'icmp6.type': '128', 'icmp6.code': '0',
      'arp.op': '1'
    };
    const commonValues = {
      'eth.type': ['0x0800', '0x86dd', '0x0806'],
      'ip.proto': ['6', '17', '1', '58'],
      'tcp.src': ['80', '443'],
      'tcp.dst': ['80', '443'],
      'udp.src': ['53', '67', '68'],
      'udp.dst': ['53', '67', '68'],
      'icmp4.type': ['8', '0'],
      'icmp6.type': ['128', '129'],
      'arp.op': ['1', '2']
    };
    commonValues[field]?.forEach(value => {
      if (!values.includes(value)) values.push(value);
    });
    row.querySelector('[data-trace-value]').placeholder = values.length
      ? 'Choose or enter value'
      : (examples[field] ? 'e.g. ' + examples[field] : 'Enter OVN value');
  }
  function refreshExtraTraceFields() {
    let context = traceFieldContext();
    context.fields.forEach(row => {
      const select = row.querySelector('[data-trace-field]');
      const previous = select.value;
      const allowed = availableTraceFields(context, row);
      select.replaceChildren(new Option('Choose a compatible field', ''));
      allowed.forEach(name => select.add(new Option(name, name)));
      if (allowed.includes(previous)) select.value = previous;
      else {
        select.value = '';
        row.querySelector('[data-trace-value]').value = '';
      }
    });
    context = traceFieldContext();
    context.fields.forEach(row => {
      const previous = row.querySelector('[data-trace-field]').value;
      const allowed = availableTraceFields(context, row);
      if (previous && !allowed.includes(previous)) {
        row.querySelector('[data-trace-field]').value = '';
        row.querySelector('[data-trace-value]').value = '';
      }
      updateExtraFieldSuggestions(row);
    });
  }
  function addExtraTraceField() {
    const rows = document.querySelectorAll('.trace-extra-row');
    if (rows.length >= 12) {
      $('trace-status').className = 'err';
      $('trace-status').textContent = 'A maximum of 12 extra trace fields is supported.';
      return;
    }
    const row = document.createElement('div');
    const listId = 'trace-extra-values-' + Date.now() + '-' + rows.length;
    row.className = 'trace-extra-row';
    row.innerHTML =
      '<label>Field <select data-trace-field required><option value="">Choose a compatible field</option></select></label>' +
      '<label>Operator <select data-trace-operator><option>==</option><option>!=</option><option>&lt;=</option><option>&gt;=</option><option>&lt;</option><option>&gt;</option></select></label>' +
      '<label>Value <input data-trace-value list="' + listId + '" required placeholder="Enter OVN value"></label>' +
      '<datalist id="' + listId + '"></datalist>' +
      '<button type="button" data-remove-trace-field aria-label="Remove trace field">Remove</button>';
    const field = row.querySelector('[data-trace-field]');
    field.addEventListener('change', () => {
      row.querySelector('[data-trace-value]').value = '';
      refreshExtraTraceFields();
    });
    row.querySelector('[data-trace-value]').addEventListener('input', refreshExtraTraceFields);
    row.querySelector('[data-trace-value]').addEventListener('change', refreshExtraTraceFields);
    row.querySelector('[data-remove-trace-field]').addEventListener('click', () => {
      row.remove();
      refreshExtraTraceFields();
    });
    $('trace-extra-fields').append(row);
    refreshExtraTraceFields();
    field.focus();
  }
  $('trace-add-field').addEventListener('click', addExtraTraceField);
  async function loadTraceOptions() {
    try {
      const response = await fetch('/trace-options', { cache: 'no-store' });
      if (!response.ok) throw new Error('HTTP ' + response.status);
      const result = await response.json();
      traceDatapaths = result.datapaths || [];
      const selected = $('trace-datapath').value;
      setSelect('trace-datapath', traceDatapaths.length ? 'Choose datapath' : 'No datapaths found',
        traceDatapaths.map(item => ({
          label: item.name + ' (' + item.kind + ')',
          value: item.name
        })), selected);
      traceVersion = result.version;
      updateTraceFields();
    } catch (err) {
      $('trace-status').className = 'err';
      $('trace-status').textContent = 'Could not load OVN trace options: ' + err.message;
    }
  }
  $('trace-datapath').addEventListener('change', updateTraceFields);
  ['trace-src-ip', 'trace-dst-ip'].forEach(id => $(id).addEventListener('change', refreshExtraTraceFields));
  ['trace-inport', 'trace-src-mac', 'trace-dst-mac', 'trace-src-ip', 'trace-dst-ip']
    .forEach(id => $(id).addEventListener('change', () => {
      $('trace-submit').disabled = !(
        $('trace-inport').value && $('trace-src-mac').value && $('trace-dst-mac').value
      );
    }));

  function parseTraceStages(output) {
    const stages = [], stack = [];
    let packetHeader = '';
    output.split(/\r?\n/).forEach(line => {
      const text = line.trim();
      if (!packetHeader && /^#\s/.test(text)) packetHeader = text.slice(1).trim();
      const header = text.match(/^(ingress|egress)\((.*)\)\s*\{$/);
      if (header) {
        const fields = {};
        for (const match of header[2].matchAll(/(\w+)="([^"]*)"/g)) fields[match[1]] = match[2];
        const stage = { pipeline: header[1], datapath: fields.dp, ...fields, actions: [] };
        stages.push(stage);
        stack.push(stage);
      } else if (text === '}' || text === '};') {
        stack.pop();
      } else if (stack.length && text) {
        stack[stack.length - 1].actions.push(text);
      }
    });
    return { stages, packetHeader };
  }

  function traceActionDescriptions(stage, ttl) {
    const descriptions = [];
    let currentTtl = ttl;
    for (const action of stage.actions) {
      if (/^reg\d+|^xreg\d+|^xxreg\d+|^flags\./.test(action) ||
          action === 'next;' || action === 'ct_clear;') continue;
      if (/check_(in|out)_port_sec\(\)/.test(action)) {
        descriptions.push(action.includes('in_port')
          ? 'OVN checks the packet against the incoming port’s security settings.'
          : 'OVN checks the packet against the outgoing port’s security settings.');
      } else if (action === 'ip.ttl--;') {
        descriptions.push(currentTtl === null
          ? 'The router decreases the IPv4 TTL by one.'
          : `The router decreases the IPv4 TTL from ${currentTtl} to ${Math.max(0, currentTtl - 1)}.`);
        if (currentTtl !== null) currentTtl = Math.max(0, currentTtl - 1);
      } else if (/^eth\.src\s*=/.test(action)) {
        descriptions.push(`Sets the Ethernet source address to ${action.replace(/^eth\.src\s*=\s*/, '').replace(/;$/, '')}.`);
      } else if (/^eth\.dst\s*=/.test(action)) {
        descriptions.push(`Sets the Ethernet destination address to ${action.replace(/^eth\.dst\s*=\s*/, '').replace(/;$/, '')}.`);
      } else if (/^ip[46]?\.dst\s*=/.test(action)) {
        descriptions.push(`Changes the packet destination IP: ${action.replace(/;$/, '')}.`);
      } else if (/^ip[46]?\.src\s*=/.test(action)) {
        descriptions.push(`Changes the packet source IP: ${action.replace(/;$/, '')}.`);
      } else if (/ct_snat|ct_dnat/.test(action)) {
        descriptions.push(`Applies connection-tracked address translation: ${action.replace(/;$/, '')}.`);
      } else if (/^drop(?:;|\s)/.test(action)) {
        descriptions.push('OVN drops the packet at this stage.');
      } else if (/^reject(?:;|\s)/.test(action)) {
        descriptions.push('OVN rejects the packet at this stage.');
      } else if (/^\/\* output to /.test(action)) {
        const output = action.match(/output to "([^"]+)", type "([^"]*)"/);
        if (output && output[2] === 'patch') {
          descriptions.push(`Continues over the OVN logical patch connection “${output[1]}” to the next logical datapath; this is not a physical cable.`);
        } else if (output) {
          descriptions.push(`Delivers the packet to logical port “${output[1]}”.`);
        } else {
          descriptions.push(action.replace(/^\/\*|\*\/;?$/g, '').trim());
        }
      } else if (action === 'output;') {
        descriptions.push(stage.outport
          ? `Sends the packet to the selected logical port “${stage.outport}”.`
          : 'Outputs the packet from this logical stage.');
      } else if (/^(?:ct_|arp|nd_|icmp|put_|push|pop|clone|check_pkt_larger)/.test(action)) {
        descriptions.push(`OVN action: ${action.replace(/;$/, '')}.`);
      }
    }
    return { descriptions, ttl: currentTtl };
  }

  function appendText(parent, tag, text, className) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    node.textContent = text;
    parent.append(node);
    return node;
  }

  function renderTraceWorkflow(trace) {
    const workflow = $('trace-workflow');
    workflow.replaceChildren();
    workflow.hidden = false;
    const parsed = parseTraceStages(trace.output);
    const input = document.createElement('div');
    input.className = 'trace-input-summary';
    [
      ['Datapath', trace.datapath],
      ['Ingress port', trace.inport],
      ['Ethernet source', trace.srcMac],
      ['Ethernet destination', trace.dstMac],
      trace.srcIp ? ['IP source', trace.srcIp] : null,
      trace.dstIp ? ['IP destination', trace.dstIp] : null
    ].filter(Boolean).forEach(([label, value]) => {
      const chip = document.createElement('span');
      chip.className = 'trace-chip';
      chip.textContent = `${label}: ${value}`;
      input.append(chip);
    });
    workflow.append(input);
    const flowDetails = document.createElement('details');
    flowDetails.className = 'trace-flow-details';
    appendText(flowDetails, 'summary', 'Show complete packet fields');
    appendText(flowDetails, 'pre', trace.flow);
    workflow.append(flowDetails);

    if (!parsed.stages.length) {
      appendText(workflow, 'p',
        'The trace returned no recognizable logical pipeline stages. Open the raw output below to inspect the result.',
        'trace-result trace-result-info');
      return;
    }

    const allActions = parsed.stages.flatMap(stage => stage.actions);
    const wasDropped = allActions.some(action => /^drop(?:;|\s)/.test(action));
    const wasRejected = allActions.some(action => /^reject(?:;|\s)/.test(action));
    const delivery = allActions.find(action => /^\/\* output to /.test(action) &&
      !/type "patch"/.test(action));
    let outcome, outcomeClass;
    if (wasDropped) {
      outcome = 'Packet dropped: the logical pipeline contains a drop action.';
      outcomeClass = 'trace-result trace-result-drop';
    } else if (wasRejected) {
      outcome = 'Packet rejected: the logical pipeline contains a reject action.';
      outcomeClass = 'trace-result trace-result-drop';
    } else if (delivery) {
      const target = delivery.match(/output to "([^"]+)"/);
      outcome = `Logical delivery reached ${target ? `port “${target[1]}”` : 'a logical port'}. This does not prove a real VM received the packet.`;
      outcomeClass = 'trace-result';
    } else {
      outcome = 'Trace completed. Review the final workflow step and raw output to determine the terminal action.';
      outcomeClass = 'trace-result trace-result-info';
    }
    appendText(workflow, 'p', outcome, outcomeClass);
    appendText(workflow, 'p',
      'Read from top to bottom. Internal register assignments are omitted; expand raw output for full OVN pipeline detail.',
      'trace-workflow-help');

    const initialTtlMatch = parsed.packetHeader.match(/nw_ttl=(\d+)/);
    let currentTtl = initialTtlMatch ? Number(initialTtlMatch[1]) : null;
    const steps = document.createElement('div');
    steps.className = 'trace-steps';
    parsed.stages.forEach((stage, index) => {
      const step = document.createElement('div');
      const actionResult = traceActionDescriptions(stage, currentTtl);
      const actions = actionResult.descriptions;
      currentTtl = actionResult.ttl;
      const terminal = actions.some(action => action.includes('drops the packet') || action.includes('rejects the packet'));
      const delivered = actions.some(action => action.startsWith('Delivers the packet'));
      step.className = 'trace-step' + (terminal ? ' trace-drop' : delivered ? ' trace-delivery' : '');
      const marker = appendText(step, 'span', String(index + 1), 'trace-step-marker');
      marker.setAttribute('aria-hidden', 'true');
      const card = document.createElement('article');
      card.className = 'trace-step-card';
      const kind = stage.pipeline === 'ingress' ? 'Enter logical datapath' : 'Process logical output';
      appendText(card, 'h4', kind);
      const location = stage.pipeline === 'ingress'
        ? `${stage.datapath || 'datapath'} · incoming port: ${stage.inport || 'unknown'}`
        : `${stage.datapath || 'datapath'} · ${stage.inport || 'unknown'} → ${stage.outport || 'selected output'}`;
      appendText(card, 'div', location, 'trace-step-location');
      if (actions.length) {
        const list = document.createElement('ul');
        actions.forEach(description => appendText(list, 'li', description));
        card.append(list);
      } else {
        appendText(card, 'p', 'OVN processed this pipeline stage; no packet change or delivery action needs highlighting here.', 'trace-note');
      }
      step.append(card);
      steps.append(step);
    });
    workflow.append(steps);
  }

  $('trace-form').addEventListener('submit', async e => {
    e.preventDefault();
    const button = $('trace-submit'), status = $('trace-status'), output = $('trace-output');
    const datapath = $('trace-datapath').value;
    const inport = $('trace-inport').value;
    const srcMac = $('trace-src-mac').value, dstMac = $('trace-dst-mac').value;
    const srcIp = $('trace-src-ip').value, dstIp = $('trace-dst-ip').value;
    if (srcIp && dstIp && srcIp.includes(':') !== dstIp.includes(':')) {
      status.className = 'err';
      status.textContent = 'Source and destination IPs must use the same address family.';
      return;
    }
    const quoteFlowString = value => '"' + value.replace(/\\/g, '\\\\').replace(/"/g, '\\"') + '"';
    const flow = [
      'inport == ' + quoteFlowString(inport),
      'eth.src == ' + srcMac,
      'eth.dst == ' + dstMac
    ];
    if (srcIp) flow.push((srcIp.includes(':') ? 'ip6.src' : 'ip4.src') + ' == ' + srcIp);
    if (dstIp) flow.push((dstIp.includes(':') ? 'ip6.dst' : 'ip4.dst') + ' == ' + dstIp);
    for (const row of document.querySelectorAll('.trace-extra-row')) {
      const field = row.querySelector('[data-trace-field]').value.trim();
      const operator = row.querySelector('[data-trace-operator]').value;
      const value = row.querySelector('[data-trace-value]').value.trim();
      if (!field || !value) {
        status.className = 'err';
        status.textContent = 'Each added trace field needs both a field name and value.';
        return;
      }
      const flowValue = field === 'inport' ? quoteFlowString(value) : value;
      flow.push(field + ' ' + operator + ' ' + flowValue);
    }
    button.disabled = true;
    status.className = '';
    status.textContent = 'Running ovn-trace...';
    $('trace-workflow').hidden = true;
    $('trace-raw-details').open = false;
    output.textContent = '';
    try {
      const response = await fetch('/ovn-trace', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          datapath,
          microflow: flow.join(' && ')
        })
      });
      const result = await response.json();
      if (!response.ok) {
        status.className = 'err';
        status.textContent = result.error || 'ovn-trace failed.';
        output.textContent = result.output || '';
        $('trace-raw-details').open = !!result.output;
      } else {
        status.textContent = 'Completed (exit code ' + result.returncode + ').';
        output.textContent = result.output || '(ovn-trace returned no output)';
        renderTraceWorkflow({
          datapath, inport, srcMac, dstMac, srcIp, dstIp,
          flow: flow.join(' && '),
          output: result.output || ''
        });
      }
    } catch (err) {
      status.className = 'err';
      status.textContent = 'Could not run ovn-trace: ' + err.message;
    } finally {
      button.disabled = false;
    }
  });

  // ---------------- dashboard tiles ----------------
  const TILES = [
    ['routers', 'Routers', '#8b5cf6'], ['switches', 'Switches', '#0ea5e9'], ['chassis', 'Chassis', '#f59e0b'],
    ['provider_networks', 'Provider nets', '#ec4899'],
    ['ports_up', 'Ports UP', '#22c55e', 'up'], ['ports_down', 'Ports DOWN', '#ef4444', 'down'],
  ];
  function renderTiles(st) {
    $('chips').innerHTML = TILES.map(([key, name, color, flt]) => {
      const v = st[key] ?? 0;
      const cls = ['tile', flt ? 'click' : '', flt && F.status === flt ? 'active' : '', flt === 'down' && v > 0 ? 'alarm' : ''].join(' ');
      return `<div class="${cls}" ${flt ? `data-flt="${flt}"` : ''}><span class="led" style="background:${color};color:${color}"></span><b>${v}</b>${name}</div>`;
    }).join('');
  }
  $('chips').addEventListener('click', e => {      // click UP / DOWN tile = filter ports by status
    const tile = e.target.closest('.tile[data-flt]');
    if (!tile) return;
    F.status = F.status === tile.dataset.flt ? 'all' : tile.dataset.flt;
    saveF(); syncUI(); apply(); renderTiles(lastStats);
  });
  let lastStats = {};

  // ---------------- live updates ----------------
  async function loadSvg(version) {
    const prev = pz ? { zoom: pz.getZoom(), pan: pz.getPan() } : null;
    try { if (pz) pz.destroy(); } catch (e) {}
    pz = null; clientErr = '';
    let svg;
    if (window.OVN_RENDERER === 'mermaid') {
      try {
        if (!window.mermaid) throw new Error('Mermaid library not loaded (CDN blocked?)');
        const response = await fetch('/diagram.mmd?v=' + version);
        if (!response.ok) throw new Error('Could not fetch Mermaid diagram: HTTP ' + response.status);
        window.mermaid.initialize({
          startOnLoad: false,
          theme: 'dark',
          themeVariables: {
            background: '#0b1220',
            primaryColor: '#1e293b',
            primaryTextColor: '#e2e8f0',
            lineColor: '#64748b'
          }
        });
        svg = (await window.mermaid.render('ovn-topology-' + version, await response.text())).svg;
      } catch (e) {
        showErr('Mermaid render error: ' + e.message);
        return;
      }
    } else {
      svg = await (await fetch('/diagram.svg?v=' + version)).text();
    }
    $('diagram').innerHTML = svg;
    const el = $('diagram').querySelector('svg');
    if (!el) return;
    // The filter must not depend on the pan/zoom library being available.
    try { buildIndex(); apply(); } catch (e) { showErr('Filter error: ' + e.message); }
    try {
      if (typeof svgPanZoom === 'undefined') throw new Error('svg-pan-zoom library not loaded (CDN blocked?)');
      pz = svgPanZoom(el, { zoomEnabled: true, controlIconsEnabled: true, fit: true, center: true,
                            minZoom: 0.05, maxZoom: 20, dblClickZoomEnabled: false });
      if (prev) { pz.zoom(prev.zoom); pz.pan(prev.pan); }
      $('diagram').ondblclick = () => { if (pz) { pz.resize(); pz.fit(); pz.center(); } };
    } catch (e) { showErr('Pan/zoom unavailable: ' + e.message); }
  }

  async function tick() {
    try {
      const s = await (await fetch('/status', { cache: 'no-store' })).json();
      lastStats = s.stats || {}; renderTiles(lastStats);
      if (s.trace_version !== traceVersion) await loadTraceOptions();
      const banner = $('banner');
      const msg = s.error ? 'OVN query failed (showing last good diagram): ' + s.error : clientErr;
      banner.style.display = msg ? 'block' : 'none';
      banner.textContent = msg;
      if (s.version > 0 && s.version !== current) { current = s.version; await loadSvg(s.version); }
      const st = $('status');
      st.className = 'status' + (s.error ? ' err' : '');
      st.textContent = s.version > 0 ? 'v' + s.version + ' · changed ' + new Date(s.updated * 1000).toLocaleTimeString()
                                     : 'Waiting for first data...';
    } catch (e) {
      $('status').className = 'status err';
      $('status').textContent = 'Connection lost. Retrying...';
    }
  }
  syncUI();
  setInterval(tick, 1000); tick();

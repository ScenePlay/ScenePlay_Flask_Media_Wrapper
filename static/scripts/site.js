var colorhex = "#FF0000";
var color = "#FF0000";
//var colorObj = w3color(color);

function sleep(ms) {
  return new Promise(resolve => setTimeout(resolve, ms));
}
function campaignChange(){
  var ev = event.target;
  jsn = {campaign_id:ev.value}
  // console.log(JSON.stringify(jsn))
  saveCampaignChange(JSON.stringify(jsn))
}      
function saveCampaignChange(json) {
  fetch('/api/campaignSelect', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: json
  }).then(() => {
    location.reload();
  }).catch(error => {
    console.error('Error:', error);
  });
}

// ANY click on a campaign dropdown dismisses the failure badges instantly —
// including re-selecting the CURRENT campaign, which fires no change event
// (that gap made the badges look unclearable). The server clears the flags;
// the DOM hides the badges without waiting for a reload. A NEW failure after
// this re-raises its badge — that's the recording architecture, not staleness.
document.addEventListener('click', function (e) {
  var t = e.target;
  if (!t || !t.closest) return;
  var sel = t.closest('select');
  if (!sel) return;
  var oc = sel.getAttribute('onchange') || '';
  if (sel.id === 'campaignDropdown' || oc.indexOf('campaignChange') !== -1) {
    try { fetch('/api/alertsClear', { method: 'POST' }); } catch (err) {}
    document.querySelectorAll('[data-sp-alert]').forEach(function (el) {
      (el.closest('a') || el).style.display = 'none';
    });
  }
});

function sceneFilterChange(){
  var ev = event.target;
  jsn = {scene_id:ev.value}
  // console.log(JSON.stringify(jsn))
  saveSceneFilter(JSON.stringify(jsn))
} 

function saveSceneFilter(json) {
  fetch('/api/sceneFilter', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: json
  }).then(() => {
    location.reload();
  }).catch(error => {
    console.error('Error:', error);
  });
}


let _volTimer = null;
function volumeChange(){
  const slider  = document.getElementById("volume_slider");
  const volume  = slider.value;
  document.getElementById("volume").textContent = "Master Volume: " + volume;
  clearTimeout(_volTimer);
  _volTimer = setTimeout(() => {
    fetch("/set_volume", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({ volume: parseInt(volume) })
    });
  }, 120);
}

function nextSong(){

  const Click = function(){
      fetch("/nextsong", {
          method: "POST",
          body: "",
          headers: {
          "Content-Type": "application/json" 
      }
      }).then(response => response.text()).then(data => console.log(data));
  }
  Click()
  sleep(2000)//.then(() => window.location.reload());
}

function songAndVideoCount(){
  const Click = function(){
      fetch("/api/songandvideocount", {
          method: "GET",
          headers: {
          "Content-Type": "application/json" 
      }
      })
      .then(response => response.text())
      .then(data => {
         const dataObj = JSON.parse(data);
         //console.log(dataObj);
         document.getElementById("songQueueCount").textContent =  "Songs: " + (dataObj[0].songQCnt || 0) + fmtQueueDur(dataObj[0].songQDur);
         document.getElementById("videoQueueCount").textContent = "Video: " + (dataObj[1].videoQCnt || 0) + fmtQueueDur(dataObj[1].videoQDur);
       });
  }
  Click()
}

// 7371 -> "2:02:51", 178 -> "2:58". Empty when no metadata duration yet.
function fmtDur(sec) {
  if (sec === null || sec === undefined || sec === '' || isNaN(sec)) return '';
  sec = Math.round(sec);
  const h = Math.floor(sec / 3600), m = Math.floor((sec % 3600) / 60), s = sec % 60;
  return h > 0 ? h + ':' + String(m).padStart(2, '0') + ':' + String(s).padStart(2, '0')
               : m + ':' + String(s).padStart(2, '0');
}

// Pill-bar suffix: " (2h 03m)" / " (23m)". Must match the Jinja render in base.html.
function fmtQueueDur(sec) {
  if (!sec || sec < 60) return '';
  const h = Math.floor(sec / 3600), m = Math.floor((sec % 3600) / 60);
  return h > 0 ? ' (' + h + 'h ' + String(m).padStart(2, '0') + 'm)' : ' (' + m + 'm)';
}

// /api/mediameta/<type>/<id>, cached per item — the now-playing hover would
// otherwise refetch on every mouseenter. Failed fetches are evicted so a
// server hiccup doesn't cache as permanent "no metadata".
const _metaCache = {};
function fetchMediaMeta(mediaType, mediaId) {
  const key = mediaType + '/' + mediaId;
  if (!_metaCache[key]) {
    _metaCache[key] = fetch('/api/mediameta/' + key).then(r => r.json());
    _metaCache[key].catch(() => delete _metaCache[key]);
  }
  return _metaCache[key];
}

// Metadata card shared by the table Info modal and the now-playing hover.
// Built with textContent — titles and descriptions come from YouTube and must
// not be injected as HTML. opts.hover trims it to tooltip size.
function buildMetaCard(meta, opts) {
  opts = opts || {};
  const card = document.createElement('div');

  if (!meta) {
    const p = document.createElement('p');
    p.textContent = 'No metadata extracted for this item yet.';
    p.style = 'margin:0;';
    card.appendChild(p);
    return card;
  }

  if (meta.thumbnail) {
    const img = document.createElement('img');
    img.src = meta.thumbnail;
    img.style = 'width:100%;border-radius:6px;margin-bottom:10px;';
    card.appendChild(img);
  }
  const h = document.createElement(opts.hover ? 'h6' : 'h4');
  h.textContent = meta.title || '(no title)';
  card.appendChild(h);

  const rows = [
    ['Uploader', meta.uploader],
    ['Uploaded', meta.upload_date ? String(meta.upload_date).replace(/^(\d{4})(\d{2})(\d{2})$/, '$1-$2-$3') : null],
    ['Length', fmtDur(meta.duration)],
    ['Views', meta.view_count != null ? Number(meta.view_count).toLocaleString() : null],
    ['Categories', meta.categories ? JSON.parse(meta.categories).join(', ') : null],
    ['Extracted', meta.extracted_at],
    ['Last error', meta.last_error],
  ];
  const tbl = document.createElement('table');
  tbl.style = 'font-size:.9em;margin-bottom:10px;';
  rows.forEach(([label, val]) => {
    if (!val) return;
    const tr = document.createElement('tr');
    const td1 = document.createElement('td');
    td1.textContent = label;
    td1.style = 'color:var(--sp-muted, #999);padding-right:12px;border:none;vertical-align:top;';
    const td2 = document.createElement('td');
    td2.textContent = val;
    td2.style = 'border:none;';
    tr.appendChild(td1); tr.appendChild(td2); tbl.appendChild(tr);
  });
  card.appendChild(tbl);

  if (meta.description) {
    const desc = document.createElement('div');
    desc.textContent = meta.description;
    // hover popover has pointer-events:none, so its description can't scroll — clip it
    desc.style = 'white-space:pre-wrap;font-size:.85em;color:var(--sp-muted, #bbb);'
               + (opts.hover ? 'max-height:90px;overflow:hidden;' : 'max-height:200px;overflow-y:auto;');
    card.appendChild(desc);
  }
  return card;
}

// Info modal for the media tables (click).
function showMediaMeta(mediaType, mediaId) {
  fetchMediaMeta(mediaType, mediaId)
    .then(meta => {
      const old = document.getElementById('mediaMetaOverlay');
      if (old) old.remove();

      const overlay = document.createElement('div');
      overlay.id = 'mediaMetaOverlay';
      overlay.style = 'position:fixed;inset:0;background:rgba(0,0,0,.6);z-index:1050;display:flex;align-items:center;justify-content:center;';
      overlay.onclick = ev => { if (ev.target === overlay) overlay.remove(); };

      const card = document.createElement('div');
      card.style = 'background:var(--sp-bg, #222);color:var(--sp-text, #eee);max-width:560px;width:90%;max-height:80vh;overflow-y:auto;border-radius:8px;padding:20px;';
      card.appendChild(buildMetaCard(meta));

      const close = document.createElement('button');
      close.textContent = 'Close';
      close.className = 'btn btn-secondary mt-2';
      close.onclick = () => overlay.remove();
      card.appendChild(close);

      overlay.appendChild(card);
      document.body.appendChild(overlay);
    })
    .catch(err => console.error('mediameta fetch failed:', err));
}

// Hover popover for the now-playing thumbnails: same card as the Info modal,
// anchored to the element and dismissed on mouseleave.
function showMetaHover(anchor, mediaType, mediaId) {
  hideMetaHover();
  fetchMediaMeta(mediaType, mediaId)
    .then(meta => {
      if (!anchor.matches(':hover')) return;   // mouse already left during fetch
      hideMetaHover();
      const pop = document.createElement('div');
      pop.id = 'mediaMetaHover';
      pop.style = 'position:fixed;z-index:1060;width:320px;max-height:70vh;overflow:hidden;'
                + 'background:var(--sp-bg, #222);color:var(--sp-text, #eee);'
                + 'border:1px solid var(--sp-muted, #555);border-radius:8px;padding:12px;'
                + 'box-shadow:0 4px 16px rgba(0,0,0,.5);pointer-events:none;';
      pop.appendChild(buildMetaCard(meta, {hover: true}));
      document.body.appendChild(pop);
      // below the anchor, flipped above if it would run off-screen
      const rect = anchor.getBoundingClientRect();
      let top = rect.bottom + 8;
      if (top + pop.offsetHeight > window.innerHeight - 8) {
        top = Math.max(8, rect.top - pop.offsetHeight - 8);
      }
      pop.style.top = top + 'px';
      pop.style.left = Math.max(8, Math.min(rect.left, window.innerWidth - 336)) + 'px';
    })
    .catch(err => console.error('mediameta fetch failed:', err));
}

function hideMetaHover() {
  const old = document.getElementById('mediaMetaHover');
  if (old) old.remove();
}

// ── Media picker (scene tables) ──────────────────────────────────────────
// ONE shared floating panel with search + thumb rows. Per-row <select>s each
// cloning the full media list into their own options were what crashed big
// pages — this list exists once, only while the picker is open, and its
// thumbnails load lazily as the user scrolls.

function shortMediaName(name, max) {
  max = max || 48;
  name = name || '';
  return name.length > max ? name.slice(0, max - 1) + '…' : name;
}

// Stored thumbs are often maxresdefault (huge); list rows only need the small
// variant. Non-YouTube URLs pass through untouched.
function spSmallThumb(url) {
  return url ? url.replace('/maxresdefault.', '/mqdefault.') : null;
}

let _pickerCleanup = null;

function spCloseMediaPicker() {
  const p = document.getElementById('spMediaPicker');
  if (p) p.remove();
  if (_pickerCleanup) { _pickerCleanup(); _pickerCleanup = null; }
}

// opts: {items, current, getId(it), getName(it), getThumb(it), getDur(it),
//        onPick(id, itemOrNull)} — onPick fires with item null for "— none —".
function spOpenMediaPicker(anchor, opts) {
  spCloseMediaPicker();
  const panel = document.createElement('div');
  panel.id = 'spMediaPicker';

  const search = document.createElement('input');
  search.type = 'search';
  search.placeholder = 'Filter…';
  panel.appendChild(search);

  const list = document.createElement('div');
  list.className = 'sp-picker-list';
  panel.appendChild(list);

  const addRow = (id, name, thumb, dur, item) => {
    const row = document.createElement('div');
    row.className = 'sp-picker-row' + (parseInt(id) === parseInt(opts.current) ? ' current' : '');
    if (thumb) {
      const img = document.createElement('img');
      img.src = thumb;
      img.loading = 'lazy';
      row.appendChild(img);
    }
    const nm = document.createElement('span');
    nm.className = 'nm';
    nm.textContent = name;
    row.appendChild(nm);
    if (dur) {
      const d = document.createElement('span');
      d.className = 'dur';
      d.textContent = dur;
      row.appendChild(d);
    }
    row.onclick = () => { spCloseMediaPicker(); opts.onPick(id, item); };
    list.appendChild(row);
  };

  addRow(0, '— none —', null, '', null);
  opts.items.forEach(it => addRow(opts.getId(it), opts.getName(it), opts.getThumb(it),
                                  opts.getDur ? opts.getDur(it) : '', it));

  document.body.appendChild(panel);

  // below the anchor, flipped above if it would run off-screen (as meta hover)
  const rect = anchor.getBoundingClientRect();
  let top = rect.bottom + 6;
  if (top + panel.offsetHeight > window.innerHeight - 8) {
    top = Math.max(8, rect.top - panel.offsetHeight - 6);
  }
  panel.style.top = top + 'px';
  panel.style.left = Math.max(8, Math.min(rect.left, window.innerWidth - panel.offsetWidth - 16)) + 'px';

  search.addEventListener('input', () => {
    const q = search.value.toLowerCase();
    list.querySelectorAll('.sp-picker-row').forEach(r => {
      r.style.display = r.textContent.toLowerCase().includes(q) ? '' : 'none';
    });
  });
  search.focus();
  const cur = list.querySelector('.current');
  if (cur) list.scrollTop = cur.offsetTop - list.clientHeight / 2;

  const onDocClick = ev => {
    if (!panel.contains(ev.target) && !anchor.contains(ev.target)) spCloseMediaPicker();
  };
  const onKey = ev => { if (ev.key === 'Escape') spCloseMediaPicker(); };
  // defer so the click that opened the picker doesn't instantly close it
  setTimeout(() => document.addEventListener('click', onDocClick), 0);
  document.addEventListener('keydown', onKey);
  _pickerCleanup = () => {
    document.removeEventListener('click', onDocClick);
    document.removeEventListener('keydown', onKey);
  };
}

// ── Multi-select delete (all gridjs tables) ─────────────────────────────
// A checkbox column feeds a Set of selected pks; "Delete Selected" loops the
// table's EXISTING single-delete endpoint, so no new backend routes. The Set
// survives gridjs page re-renders (formatters re-check from it), so a
// selection can span pages. Ids stay strings — several delrow endpoints
// concatenate them into reply text and would choke on ints.
const spDelSel = new Set();
let spBulkCfg = null;

function spCheckHtml(id) {
  return '<input type="checkbox" class="sp-row-check" data-id="' + id + '"'
       + (spDelSel.has(String(id)) ? ' checked' : '') + ' onchange="spRowCheck(this)">';
}

function spRowCheck(cb) {
  if (cb.checked) spDelSel.add(String(cb.dataset.id));
  else spDelSel.delete(String(cb.dataset.id));
  spUpdateDelBtn();
}

function spUpdateDelBtn() {
  const btn = document.getElementById('spDelSelectedBtn');
  if (!btn) return;
  btn.value = 'Delete Selected (' + spDelSel.size + ')';
  btn.disabled = spDelSel.size === 0;
}

// Toggle every checkbox on the current page (all on unless all already on).
function spSelectPage() {
  const boxes = document.querySelectorAll('.sp-row-check');
  const allChecked = boxes.length > 0 && [...boxes].every(cb => cb.checked);
  boxes.forEach(cb => { cb.checked = !allChecked; spRowCheck(cb); });
}

async function spDeleteSelected() {
  const n = spDelSel.size;
  if (!n || !spBulkCfg) return;
  if (!confirm('Delete ' + n + ' selected row' + (n > 1 ? 's' : '') + '?')) return;
  const btn = document.getElementById('spDelSelectedBtn');
  btn.disabled = true;
  btn.value = 'Deleting…';
  let failed = 0;
  for (const id of spDelSel) {           // sequential — media deletes remove files
    try {
      const r = await fetch(spBulkCfg.endpoint, {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({[spBulkCfg.primeKey]: id}),
      });
      if (!r.ok) failed++;
    } catch (e) { failed++; }
  }
  if (failed) alert(failed + ' of ' + n + ' deletes failed.');
  spDelSel.clear();
  window.location.reload();
}

// Insert the Select Page / Delete Selected buttons next to the gridjs search
// box (same slot the Add New Row buttons use). Retries briefly because the
// grid renders asynchronously after page load.
function spInitBulkDelete(endpoint, primeKey) {
  spBulkCfg = {endpoint: endpoint, primeKey: primeKey};
  const tryInsert = attempts => {
    const anchor = document.querySelector('div.gridjs-search');
    if (!anchor) {
      if (attempts > 0) setTimeout(() => tryInsert(attempts - 1), 200);
      return;
    }
    if (document.getElementById('spDelSelectedBtn')) return;
    const delBtn = document.createElement('input');
    delBtn.type = 'button';
    delBtn.id = 'spDelSelectedBtn';
    delBtn.className = 'btn btn-danger';
    delBtn.value = 'Delete Selected (0)';
    delBtn.disabled = true;
    delBtn.style = 'float: right; margin-left: 10px;';
    delBtn.onclick = spDeleteSelected;
    const selBtn = document.createElement('input');
    selBtn.type = 'button';
    selBtn.className = 'btn btn-secondary';
    selBtn.value = 'Select Page';
    selBtn.style = 'float: right; margin-left: 10px;';
    selBtn.onclick = spSelectPage;
    anchor.parentNode.insertBefore(delBtn, anchor.nextSibling);
    anchor.parentNode.insertBefore(selBtn, anchor.nextSibling);
  };
  tryInsert(25);
}

// Refresh a picker button's face (thumb + short name) in place.
function spSetPickerBtn(btn, name, thumb) {
  const img = btn.querySelector('img');
  const span = btn.querySelector('span');
  if (span) span.textContent = name;
  if (img) {
    if (thumb) { img.src = thumb; img.style.display = ''; }
    else { img.style.display = 'none'; }
  }
}

function nextVideo(){

  const Click = function(){
      fetch("/nextvideo", {
          method: "POST",
          body: "",
          headers: {
          "Content-Type": "application/json" 
      }
      }).then(response => response.text()).then(data => console.log(data));
  }
  Click()
  sleep(2000)//.then(() => window.location.reload());
}

function killQueue(){

  const Click = function(){
      fetch("/killqueue", {
          method: "POST",
          body: "",
          headers: {
          "Content-Type": "application/json" 
      }
      }).then(response => response.text()).then(data => console.log(data));
  }
  const Click2 = function(){
    fetch("/activatescenes/?id=-1", {
        method: "POST",
        body: "",
        headers: {
        "Content-Type": "application/json" 
    }
    }).then(response => response.text()).then(data => console.log(data));
  }
  Click()
  sleep(2000)
  Click2()
  //sleep(2000).then(() => window.location.reload());
}

function mouseOverColor(hex) {
    document.getElementById("divpreview").style.visibility = "visible";
    document.getElementById("divpreview").style.backgroundColor = hex;
    document.body.style.cursor = "pointer";
}
function mouseOutMap() {
    if (hh == 0) {
        document.getElementById("divpreview").style.visibility = "hidden";
    } else {
      hh = 0;
    }
    document.getElementById("divpreview").style.backgroundColor = colorObj.toHexString();
    document.body.style.cursor = "";
}
var hh = 0;

function componentToHex(c) {
  var hex = Number(c).toString(16).toUpperCase();
  return hex.length == 1 ? "0" + hex : hex;
}

function rgbToHex(r, g, b) {
  return "#" + componentToHex(r) + componentToHex(g) + componentToHex(b);
}

function hexToRGB(hexColor){
  return {
    red: (hexColor >> 16) & 0xFF,
    green: (hexColor >> 8) & 0xFF,  
    blue: hexColor & 0xFF,
  }
}

var RGBvalues = (function() {

var _hex2dec = function(v) {
    return parseInt(v, 16)
};

var _splitHEX = function(hex) {
    var c;
    if (hex.length === 4) {
        c = (hex.replace('#','')).split('');
        return {
            r: _hex2dec((c[0] + c[0])),
            g: _hex2dec((c[1] + c[1])),
            b: _hex2dec((c[2] + c[2]))
        };
    } else {
         return {
            r: _hex2dec(hex.slice(1,3)),
            g: _hex2dec(hex.slice(3,5)),
            b: _hex2dec(hex.slice(5))
        };
    }
};

var _splitRGB = function(rgb) {
    var c = (rgb.slice(rgb.indexOf('(')+1, rgb.indexOf(')'))).split(',');
    var flag = false, obj;
    c = c.map(function(n,i) {
        return (i !== 3) ? parseInt(n, 10) : flag = true, parseFloat(n);
    });
    obj = {
        r: c[0],
        g: c[1],
        b: c[2]
    };
    if (flag) obj.a = c[3];
    return obj;
};

var color = function(col) {
    var slc = col.slice(0,1);
    if (slc === '#') {
        return _splitHEX(col);
    } else if (slc.toLowerCase() === 'r') {
        return _splitRGB(col);
    } else {
        console.log('!Ooops! RGBvalues.color('+col+') : HEX, RGB, or RGBa strings only');
    }
};

return {
    color: color
};
}());



function clickColor(hex, seltop, selleft, html5, field = '') {
    var elnt = event.target;
    console.log(elnt.id)
    //elnt
    var c, cObj, colormap, areas, i, areacolor, cc;
    if (html5 && html5 == 5)  {
        c = document.getElementById(elnt.id).value;
    } else {
        if (hex == 0)  {
            c = document.getElementById(elnt.id).value;
            c = c.replace(/;/g, ","); //replace any semicolon with a comma
        } else {
            c = hex;
        }
    }
    cObj = w3color(c);
    colorhex = cObj.toHexString();
    if (cObj.valid) {
        clearWrongInput();
    } else {
        wrongInput();
        return;
    }
    r = cObj.red;
    g = cObj.green;
    b = cObj.blue;
    id = elnt.id.split("_ID_")
    //console.log(elnt)
    rgbsave = "[" + r.toString() + "," + g.toString() + "," + b.toString() + "]"
    if(field == 'color'){
      jsn = {scenePattern_ID:id[1],color:rgbsave}
    }
    if(field == 'cdiff'){
      jsn = {scenePattern_ID:id[1],cdiff:rgbsave}
    }
    if(field == 'color1'){
      jsn = {wledPattern_ID:id[1],color1:rgbsave}
    }
    if(field == 'color2'){
      jsn = {wledPattern_ID:id[1],color2:rgbsave}
    }
    if(field == 'color3'){
      jsn = {wledPattern_ID:id[1],color3:rgbsave}
    }
    //console.log(JSON.stringify(jsn))
    
    console.log(JSON.stringify(jsn));
    saveChange(JSON.stringify(jsn))
    //document.getElementById("colornamDIV").innerHTML = (cObj.toName() || "");
    //document.getElementById("colorhexDIV").innerHTML = cObj.toHexString();
    //document.getElementById("colorrgbDIV").innerHTML = cObj.toRgbString();
    //document.getElementById("colorhslDIV").innerHTML = cObj.toHslString();    
/*     if ((!seltop || seltop == -1) && (!selleft || selleft == -1)) {
        colormap = document.getElementById("colormap");
        areas = colormap.getElementsByTagName("AREA");
        for (i = 0; i < areas.length; i++) {
            areacolor = areas[i].getAttribute("onmouseover").replace('mouseOverColor("', '');
            areacolor = areacolor.replace('")', '');
            if (areacolor.toLowerCase() == colorhex) {
                cc = areas[i].getAttribute("onclick").replace(')', '').split(",");
                seltop = Number(cc[1]);
                selleft = Number(cc[2]);
            }
        }
    } */

/*     if ((seltop+200)>-1 && selleft>-1) {
        document.getElementById("selectedhexagon").style.top=seltop + "px";
        document.getElementById("selectedhexagon").style.left=selleft + "px";
        document.getElementById("selectedhexagon").style.visibility="visible";
  } else {
        document.getElementById("divpreview").style.backgroundColor = cObj.toHexString();
        document.getElementById("selectedhexagon").style.visibility = "hidden";
  } */
    //document.getElementById("selectedcolor").style.backgroundColor = cObj.toHexString();
    //document.getElementById("html5colorpicker").value = cObj.toHexString();  
  //ocument.getElementById('slideRed').value = r;
  //document.getElementById('slideGreen').value = g;
  //document.getElementById('slideBlue').value = b;
  //changeRed(r);changeGreen(g);changeBlue(b);
  //changeColor();
  //document.getElementById("fixed").style.backgroundColor = cObj.toHexString();
}
function wrongInput() {
    document.getElementById("entercolorDIV").className = "has-error";
    document.getElementById("wronginputDIV").style.display = "block";
}
function clearWrongInput() {
    /* document.getElementById("entercolorDIV").className = "";
    docume nt.getElementById("wronginputDIV").style.display = "none"; */
}
function changeRed(value) {
    document.getElementById('valRed').innerHTML = value;
    changeAll();
}
function changeGreen(value) {
    document.getElementById('valGreen').innerHTML = value;
    changeAll();
}
function changeBlue(value) {
    document.getElementById('valBlue').innerHTML = value;
    changeAll();
}
function changeAll() {
    var r = document.getElementById('valRed').innerHTML;
    var g = document.getElementById('valGreen').innerHTML;
    var b = document.getElementById('valBlue').innerHTML;
    document.getElementById('change').style.backgroundColor = "rgb(" + r + "," + g + "," + b + ")";
    document.getElementById('changetxt').innerHTML = "rgb(" + r + ", " + g + ", " + b + ")";
    document.getElementById('changetxthex').innerHTML = w3color("rgb(" + r + "," + g + "," + b + ")").toHexString();
}

function hslLum_top() {
  var i, a, match;
  var color = document.getElementById("colorhexDIV").innerHTML;
  var hslObj = w3color(color);
  var h = hslObj.hue;
  var s = hslObj.sat;
  var l = hslObj.lightness;
  var arr = [];
  for (i = 0; i <= 20; i++) {
      arr.push(w3color("hsl(" + h + "," + s + "," + (i * 0.05) + ")"));
  }
  arr.reverse();
  a = "<h3 class='w3-center'>Lighter / Darker:</h3><table class='colorTable' style='width:100%;'>";
  match = 0;
  for (i = 0; i < arr.length; i++) {
    if (match == 0 && Math.round(l * 100) == Math.round(arr[i].lightness * 100)) {
      a += "<tr><td></td><td></td><td></td></tr>";
      a += "<tr>";
      a += "<td style='text-align:right;'><b>" + Math.round(l * 100) + "%&nbsp;</b></td>";
      a += "<td style='background-color:" + w3color(hslObj).toHexString() + "'><br><br></td>";
      a += "<td>&nbsp;<b>" + w3color(hslObj).toHexString() + "</b></td>";
      a += "</tr>";
      a += "<tr><td></td><td></td><td></td></tr>";
      match = 1;      
    } else {
      if (match == 0 && l > arr[i].lightness) {
        a += "<tr><td></td><td></td><td></td></tr>";
        a += "<tr>";
        a += "<td style='text-align:right;'><b>" + Math.round(l * 100) + "%&nbsp;</b></td>";
        a += "<td style='background-color:" + w3color(hslObj).toHexString() + "'></td>";
        a += "<td>&nbsp;<b>" + w3color(hslObj).toHexString() + "</b></td>";
        a += "</tr>";
        a += "<tr><td></td><td></td><td></td></tr>";
        match = 1;
      }
      a += "<tr>";
      a += "<td style='width:40px;text-align:right;'>" + Math.round(arr[i].lightness * 100) + "%&nbsp;</td>";
      a += "<td style='cursor:pointer;background-color:" + arr[i].toHexString() + "' onclick='clickColor(\"" + arr[i].toHexString() + "\")'></td>";
      a += "<td style='width:80px;'>&nbsp;" + arr[i].toHexString() + "</td>";
      a += "</tr>";
    }
  }
  a += "</table>";
  document.getElementById("lumtopcontainer").innerHTML = a;
}

function hslTable(x) {
  var lineno, header, i, a, match, same, comp, loopHSL, HSL;
  var color = document.getElementById("colorhexDIV").innerHTML;
  var hslObj = w3color(color);
  var h = hslObj.hue;
  var s = hslObj.sat;
  var l = hslObj.lightness;
  var arr = [];
  if (x == "hue") {header = "Hue"; lineno = 24;}
  if (x == "sat") {header = "Saturation"; lineno = 20;}
  if (x == "light") {header = "Lightness"; lineno = 20;}  
  for (i = 0; i <= lineno; i++) {
    if (x == "hue") {arr.push(w3color("hsl(" + (i * 15) + "," + s + "," + l + ")"));}
    if (x == "sat") {arr.push(w3color("hsl(" + h + "," + (i * 0.05) + "," + l + ")"));}
    if (x == "light") {arr.push(w3color("hsl(" + h + "," + s + "," + (i * 0.05) + ")"));}
  }
  if (x == "sat" || x == "light") {arr.reverse();}
  a = "<h3>" + header + "</h3>";
  a += "<div class='w3-responsive'>";
  a += "<table class='ws-table-all colorTable' style='width:100%;white-space: nowrap;font-size:14px;'>";
  a += "<tr>";
  a += "<td style='width:150px;'></td>";
  a += "<td style='text-align:right;text-transform:capitalize;'>" + x + "&nbsp;</td>";
  a += "<td>Hex</td>";
  a += "<td>Rgb</td>";
  a += "<td>Hsl</td>";
  a += "</tr>";  
  match = 0;
  for (i = 0; i < arr.length; i++) {
    same = 0;
    if (x == "hue") {
      loopHSL = w3color(arr[i]).hue;
      HSL = h;
      if (i == arr.length - 1) {loopHSL = 360;}
      comp = (loopHSL > HSL);
    }
    if (x == "sat") {
      loopHSL = Math.round(w3color(arr[i]).sat * 100);
      HSL = Number(s * 100);
      HSL = Math.round(HSL);
      comp = (loopHSL < HSL);
      HSL = HSL + "%";
      loopHSL = loopHSL + "%";
    }
    if (x == "light") {
      loopHSL = Math.round(w3color(arr[i]).lightness * 100);
      HSL = Number(l * 100);
      HSL = Math.round(HSL);      
      comp = (loopHSL < HSL);
      HSL = HSL + "%";
      loopHSL = loopHSL + "%";
    }
    if (HSL == loopHSL) {
      match++;
      same = 1;
    }
    if (comp) {match++;}
    if (match == 1) {
      a += "<tr class='ws-green'>";
      a += "<td style='background-color:" + hslObj.toHexString() + "'></td>";
      a += "<td style='text-align:right;'><b>" + HSL + "&nbsp;</b></td>";
      a += "<td><b>" + hslObj.toHexString() + "</b></td>";
      a += "<td><b>" + hslObj.toRgbString() + "</b></td>";
      a += "<td><b>" + hslObj.toHslString() + "</b></td>";
      a += "</tr>";
      match = 2;
    }
    if (same == 0) {
      a += "<tr>";
      a += "<td style='cursor:pointer;background-color:" + arr[i].toHexString() + "' onclick='clickColor(\"" + arr[i].toHexString() + "\")'></td>";
      a += "<td style='text-align:right;'>" + loopHSL + "&nbsp;</td>";
      a += "<td>" + arr[i].toHexString() + "</td>";
      a += "<td>" + arr[i].toRgbString() + "</td>";
      a += "<td>" + arr[i].toHslString() + "</td>";
      a += "</tr>";
    }
  }
  a += "</table></div>";
  if (x == "hue") {document.getElementById("huecontainer").innerHTML = a;}
  if (x == "sat") {document.getElementById("hslsatcontainer").innerHTML = a;}
  if (x == "light") {document.getElementById("hsllumcontainer").innerHTML = a;}

}
function changeColor(value) {
  hslLum_top();  
  hslTable("hue");
  hslTable("sat");
  hslTable("light");
}
window.onload = function() {
    var x = document.createElement("input");
    x.setAttribute("type", "color");
    if (x.type == "text") {
        document.getElementById("html5DIV").style.visibility = "hidden";
    }
}
function submitOnEnter(e) {
    keyboardKey = e.which || e.keyCode;
    if (keyboardKey == 13) {
        clickColor(0,-1,-1);
    }
}


// Shared by the music and video transport controls — each mpv instance has a
// twin route pair addressing its own IPC socket. The pause buttons are
// <button> elements, so the ||/▶ label lives in textContent (not .value).
function _playerStartStop(endpoint, buttonId) {
  const button = document.getElementById(buttonId);
  fetch(endpoint, { method: 'POST' })
  .then(response => response.json())
  .then(result => {
    console.log('Start/stop request successful:', result);
    button.textContent = (button.textContent.trim() === '||') ? '▶' : '||';
  })
  .catch(error => console.error('Error in start/stop request:', error));
}

function _playerSeek(endpoint, value) {
  fetch(endpoint, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ value: value })
  })
  .then(response => response.json())
  .then(result => {
    console.log('Seek request successful:', result);
  })
  .catch(error => console.error('Error in seek request:', error));
}

function videoStartStop() { _playerStartStop('/video_stopstart', 'playPauseButton'); }
function videoSeek(value) { _playerSeek('/video_seek', value); }
function musicStartStop() { _playerStartStop('/music_stopstart', 'musicPauseButton'); }
function musicSeek(value) { _playerSeek('/music_seek', value); }
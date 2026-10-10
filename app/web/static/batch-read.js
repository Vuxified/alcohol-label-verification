/* Reading a batch: the spreadsheet and the ZIP of label pictures -> one job per application.
   Kept apart from the page so it can be tested in a browser (tests/test_batch_read.py). Needs Papa (PapaParse). */
var BatchRead = (function () {
  var IMAGE = /\.(jpe?g|png|webp)$/;
  // Column names people actually use, after lower-casing and turning spaces and dashes into "_".
  var COLUMNS = {
    application_id: ['application_id', 'application', 'application_number', 'id', 'ttb_id', 'cola_id'],
    image_files: ['image_files', 'images', 'image', 'image_file', 'files', 'file_names', 'pictures'],
    beverage_type: ['beverage_type', 'beverage', 'product_type', 'type_of_product'],
    brand_name: ['brand_name', 'brand'],
    fanciful_name: ['fanciful_name', 'fanciful'],
    class_type: ['class_type', 'class', 'class_or_type', 'class_type_designation', 'type'],
    abv: ['abv', 'alcohol', 'alcohol_content', 'alc'],
    net_contents: ['net_contents', 'net', 'contents', 'size'],
    name_address: ['name_address', 'name_and_address', 'bottler', 'address'],
    source: ['source', 'domestic_or_imported'],
    country_of_origin: ['country_of_origin', 'country', 'origin'],
    label_height: ['label_height', 'label_height_in', 'label_height_inches', 'height', 'height_in', 'height_inches'],
  };
  var BEV = {
    spirits: 'spirits', spirit: 'spirits', 'distilled spirits': 'spirits', 'distilled spirit': 'spirits', liquor: 'spirits',
    wine: 'wine', malt: 'malt', beer: 'malt', 'malt beverage': 'malt', 'malt beverages': 'malt', ale: 'malt', lager: 'malt',
  };

  function header(h) { return h.normalize('NFC').trim().toLowerCase().replace(/[^a-z0-9]+/g, '_').replace(/^_+|_+$/g, ''); }

  function decode(buf) {
    var b = new Uint8Array(buf), text;
    if (b[0] === 0xFF && b[1] === 0xFE) text = new TextDecoder('utf-16le').decode(b);       // Excel "Unicode Text"
    else if (b[0] === 0xFE && b[1] === 0xFF) text = new TextDecoder('utf-16be').decode(b);
    else {
      try { text = new TextDecoder('utf-8', { fatal: true }).decode(b); }
      catch (e) { text = new TextDecoder('windows-1252').decode(b); }                       // Excel on Windows
    }
    return text.replace(/^﻿/, '');
  }

  function zipKey(path) {
    return path.normalize('NFC').replace(/\\/g, '/').replace(/^(\.\/)+/, '').replace(/^\/+/, '').toLowerCase();
  }

  // ZIP paths -> {key: entry}. Skips folders, macOS extras and hidden files, and paths that leave the ZIP.
  function entriesOf(items) {
    var out = Object.create(null);
    items.forEach(function (it) {
      if (it.dir) return;
      var raw = it.path.replace(/\\/g, '/').replace(/^(\.\/)+/, '');
      var parts = raw.split('/');
      if (parts[0] === '__MACOSX' || parts.some(function (p) { return p.startsWith('.'); })) return;
      if (parts.indexOf('..') >= 0 || it.path.startsWith('/')) return;
      out[zipKey(raw)] = it.entry;
    });
    return out;
  }

  function base(k) { return k.split('/').pop(); }
  function stem(k) { return base(k).replace(/\.[^.]+$/, ''); }

  // A file named in the spreadsheet -> {entry} or {error}. Folders inside the ZIP and .jpg/.jpeg/.png differences are fine.
  function findEntry(entries, name) {
    var n = zipKey(name.trim());
    if (entries[n]) return { entry: entries[n] };
    var keys = Object.keys(entries), hits = keys.filter(function (k) { return base(k) === base(n); });
    if (!hits.length && IMAGE.test(n)) hits = keys.filter(function (k) { return IMAGE.test(k) && stem(k) === stem(n); });
    if (hits.length === 1) return { entry: entries[hits[0]] };
    if (hits.length > 1) return { error: '"' + name.trim() + '" is in more than one folder of the ZIP; give its folder too' };
    return { error: '"' + name.trim() + '" is not in the ZIP' };
  }

  // Pictures named after the application ("TTB-0001_front.jpg"), for rows that don't list their files.
  function filesNamed(entries, id) {
    var p = id.normalize('NFC').toLowerCase();
    return Object.keys(entries).filter(function (k) {
      var b = base(k);
      return IMAGE.test(b) && b.startsWith(p) && /^[_\-. ]/.test(b.slice(p.length));
    }).sort();
  }

  function csvIn(entries) {
    if (entries['manifest.csv']) return entries['manifest.csv'];
    var csvs = Object.keys(entries).filter(function (k) { return /\.csv$/.test(k); });
    if (csvs.length === 1) return entries[csvs[0]];
    var m = csvs.filter(function (k) { return base(k) === 'manifest.csv'; });
    return m.length === 1 ? entries[m[0]] : null;
  }

  function rows(csvText, entries, limits) {
    var parsed = Papa.parse(csvText, { header: true, skipEmptyLines: 'greedy', transformHeader: header });
    var have = parsed.meta.fields || [], col = {}, problems = [];
    Object.keys(COLUMNS).forEach(function (c) {
      col[c] = COLUMNS[c].filter(function (name) { return have.indexOf(name) >= 0; })[0];
    });
    ['application_id', 'beverage_type', 'brand_name'].forEach(function (c) {
      if (!col[c]) problems.push('The spreadsheet has no "' + c + '" column.');
    });
    if (problems.length) return { fatal: problems };
    var get = function (r, c) { return col[c] ? String(r[col[c]] == null ? '' : r[col[c]]).trim() : ''; };
    if (parsed.data.length > limits.rows) problems.push('The spreadsheet has ' + parsed.data.length + ' rows. Only the first ' + limits.rows + ' will be checked.');
    var seen = {}, jobs = [];
    parsed.data.slice(0, limits.rows).forEach(function (r, i) {
      var row = i + 2, id = get(r, 'application_id'), bad = [];
      var label = id || ('row ' + row);
      if (!id) bad.push('no application_id');
      else if (seen[id]) bad.push('application_id "' + id + '" is used twice');
      seen[id] = true;
      var bev = BEV[get(r, 'beverage_type').toLowerCase()];
      if (!bev) bad.push('beverage_type "' + get(r, 'beverage_type') + '" should be spirits, wine or malt');
      if (!get(r, 'brand_name')) bad.push('no brand_name');
      var abv = get(r, 'abv');               // the server reads "45", "45%" or "45% Alc./Vol."
      if (abv && !/\d/.test(abv)) bad.push('alcohol content "' + abv + '" has no number');
      var height = get(r, 'label_height');  // inches; the server reads "4", "4.5 in" or '4.5"'
      if (height && !/\d/.test(height)) bad.push('label height "' + height + '" has no number');
      var src = get(r, 'source').toLowerCase(), country = get(r, 'country_of_origin');
      var imported = /^(imported|import|foreign)$/.test(src) || (!src && country && !/^(us|usa|u\.s\.a?\.?|united states( of america)?)$/i.test(country));
      if (src && !imported && !/^(domestic|us|usa|u\.s\.)$/.test(src)) bad.push('source "' + get(r, 'source') + '" should be domestic or imported');
      var listed = get(r, 'image_files').split(/[;,|\n]/).map(function (s) { return s.trim(); }).filter(Boolean);
      var names = listed.length ? listed : (id ? filesNamed(entries, id) : []);
      var others = bad.slice();  // the row's problems apart from having no pictures
      if (!names.length) bad.push(col.image_files ? 'no image_files, and no pictures named after "' + label + '"' : 'no pictures named after "' + label + '" in the ZIP');
      if (names.length > limits.images) bad.push(names.length + ' images (the limit is ' + limits.images + ')');
      var found = [];
      names.slice(0, limits.images).forEach(function (f) {
        var hit = findEntry(entries, f);
        if (hit.error) bad.push(hit.error);
        else if (hit.entry._data && hit.entry._data.uncompressedSize > limits.mb * 1024 * 1024) bad.push('"' + f + '" is over ' + limits.mb + ' MB');
        else found.push({ name: base(f), entry: hit.entry });
      });
      var job = { row: row, id: label, pairedBy: listed.length ? 'spreadsheet' : 'file name', files: found, form: {
        beverage_type: bev || '', brand_name: get(r, 'brand_name'), fanciful_name: get(r, 'fanciful_name'),
        class_type: get(r, 'class_type'), abv: abv, net_contents: get(r, 'net_contents'), name_address: get(r, 'name_address'),
        source: imported ? 'imported' : 'domestic', country_of_origin: country, label_height: height } };
      if (!names.length) { job.unpaired = true; job.others = others; }  // may still be paired by reading (pair)
      if (bad.length) { problems.push('Row ' + row + ' (' + label + '): ' + bad.join('; ') + '.'); job.error = bad.join('; '); }
      jobs.push(job);
    });
    return { jobs: jobs, problems: problems };
  }

  // Pictures in the ZIP that no row claims (by listing them or by their name).
  function leftovers(entries, jobs) {
    var used = new Set();
    jobs.forEach(function (j) { j.files.forEach(function (f) { used.add(f.entry); }); });
    return Object.keys(entries).filter(function (k) { return IMAGE.test(k) && !used.has(entries[k]); }).sort();
  }

  function words(t) { return ' ' + String(t || '').normalize('NFD').replace(/[\u0300-\u036f]/g, '').toLowerCase().replace(/[^a-z0-9]+/g, ' ').trim() + ' '; }
  function amount(t) {  // "750 mL" -> "750ml", "12 FL. OZ." -> "12oz"
    var m = String(t || '').toLowerCase().replace(/,/g, '.').match(/(\d+(?:\.\d+)?)\s*(ml|l|lit|fl\.?\s*oz|oz)/);
    return m ? parseFloat(m[1]) + m[2].replace(/fl\.?\s*/, '').replace('lit', 'l') : '';
  }

  // The bottler's name from the spreadsheet: "Bottled by Lantern Distilling Co., Louisville, KY" -> "lantern distilling co"
  function bottler(t) {
    var first = String(t || '').split(',')[0].replace(/^.*\b(?:by|for)\b:?/i, '');
    var w = words(first).trim();
    return w.split(' ').length >= 2 ? w : '';
  }

  // Leftover pictures, each read by the checker ({key, entry, values: {text, abv, net_contents}}), given to the rows
  // without pictures. Evidence: brand or bottler name found as whole words 2, alcohol equal 1, net contents equal 1,
  // a different alcohol or net contents -1 (contradicts). A picture goes to a row with 2 or more and no other row as
  // high, and only one row's name on it (a gift pack is unclear). A picture with less (a back label with only the size)
  // joins the row of the picture before it in file-name order (else after it), if it agrees with that row (1 or more)
  // and shows no row's name. Anything else is listed for the agent, never guessed.
  function pair(jobs, readings) {
    var open = jobs.filter(function (j) { return j.unpaired; }), unpaired = [], owner = [], named = [];
    var scored = readings.map(function (r, i) {
      var text = words(r.values.text);
      named[i] = 0;
      return open.map(function (j) {
        var s = 0, names = [words(j.form.brand_name).trim(), bottler(j.form.name_address)];
        if (names.some(function (n) { return n.length > 1 && text.indexOf(' ' + n + ' ') >= 0; })) { s += 2; named[i]++; }
        if (j.form.abv && r.values.abv) s += Math.abs(parseFloat(j.form.abv) - parseFloat(r.values.abv)) < 0.05 ? 1 : -1;
        if (j.form.net_contents && r.values.net_contents) s += amount(j.form.net_contents) === amount(r.values.net_contents) ? 1 : -1;
        return s;
      });
    });
    scored.forEach(function (scores, i) {
      var best = Math.max.apply(null, scores.concat([0]));
      var winners = open.filter(function (j, k) { return scores[k] === best; });
      owner[i] = best >= 2 && winners.length === 1 && named[i] <= 1 ? winners[0] : null;
    });
    scored.forEach(function (scores, i) {  // back labels: join the picture before (else after) if they agree
      if (owner[i] || named[i]) return;
      owner[i] = [owner[i - 1], owner[i + 1]].filter(function (j) { return j && scores[open.indexOf(j)] >= 1; })[0] || null;
    });
    readings.forEach(function (r, i) {
      if (owner[i]) owner[i].files.push({ name: (r.entry.name || r.key).split('/').pop(), entry: r.entry, read: true });
      else unpaired.push(r.entry.name);
    });
    open.forEach(function (j) {
      var msg = j.files.length ? [] : ["Couldn't pair any pictures with this application"];
      if (j.files.length) j.pairedBy = 'reading the label';
      j.error = msg.concat(j.others).join('; ') || undefined;
    });
    return { unpaired: unpaired };
  }

  return { leftovers: leftovers, pair: pair, decode: decode, entriesOf: entriesOf, findEntry: findEntry, filesNamed: filesNamed, csvIn: csvIn, rows: rows, header: header };
})();

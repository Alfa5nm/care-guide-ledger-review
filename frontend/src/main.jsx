import React, { useEffect, useRef, useState } from 'react';
import { createRoot } from 'react-dom/client';
import { flushSync } from 'react-dom';
import './style.css';

const fields = {
  invoice_number: 'Invoice number', invoice_date: 'Invoice date', supplier_name: 'Supplier',
  customer_name: 'Customer', subtotal: 'Subtotal', tax: 'Tax', total: 'Total', currency: 'Currency',
  line_items: 'Line items'
};
const itemFields = { description: 'Description', quantity: 'Qty', unit_price: 'Unit price', amount: 'Amount' };

function transition(update) {
  if (!document.startViewTransition || window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
    update();
    return;
  }
  document.startViewTransition(() => flushSync(update));
}

async function api(path, options) {
  const response = await fetch('/api' + path, options);
  const body = response.headers.get('content-type')?.includes('application/json')
    ? await response.json() : null;
  if (!response.ok || !body) throw new Error(typeof body?.detail === 'string' ? body.detail : 'Ledger Review could not complete the request. Try again.');
  return body;
}

function Icon({ name }) {
  const paths = {
    logo: ['M7 3h7l5 5v13H5V3h2z', 'M14 3v6h5M8 13h8M8 17h5'],
    documents: ['M8 3h8l4 4v13H8z', 'M5 6H4v15h12M15 3v5h5'],
    search: ['M20 20l-5-5', 'M17 10a7 7 0 1 1-14 0 7 7 0 0 1 14 0z'],
    upload: ['M12 16V3m-5 5 5-5 5 5', 'M4 16v4h16v-4'],
    arrow: ['M5 12h14m-6-6 6 6-6 6'],
    back: ['M19 12H5m6-6-6 6 6 6'],
    plus: ['M12 5v14M5 12h14'],
    compare: ['M3 7h17m-5-5 5 5-5 5M21 17H4m5-5-5 5 5 5'],
    clock: ['M12 8v4l2 2', 'M21 12a9 9 0 1 1-18 0 9 9 0 0 1 18 0z'],
    check: ['M5 12l4 4L19 6'],
    alert: ['M12 8v5m0 3v.01', 'M21 12a9 9 0 1 1-18 0 9 9 0 0 1 18 0z'],
    sidebar: ['M3 5h18v14H3zM9 5v14', 'm15 9-3 3 3 3'],
    chevron: ['m6 9 6 6 6-6'],
  };
  return <svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">{paths[name].map(path => <path key={path} d={path}/>)}</svg>;
}

function Status({ value }) {
  return <span className={'status ' + value.toLowerCase().replaceAll(' ', '-')}><i/>{value}</span>;
}

function Upload({ onUpload, notify }) {
  const input = useRef(null);
  const dragDepth = useRef(0);
  const [sending, setSending] = useState(false);
  const [dragging, setDragging] = useState(false);
  async function send(files) {
    if (!files.length || sending) return;
    if (files.length > 12) return notify('Select up to 12 files per upload.', true);
    setSending(true);
    try {
      const source = new FormData();
      Array.from(files).forEach(file => source.append('files', file));
      const result = await api('/documents', { method: 'POST', body: source });
      const queued = result.files.filter(file => file.id).length;
      const errors = result.files.filter(file => file.error).map(file => file.name + ' — ' + file.error);
      notify(queued + ' queued.' + (errors.length ? ' ' + errors.join(' · ') : ''), Boolean(errors.length));
      onUpload();
    } catch (error) {
      notify(error.message, true);
    } finally {
      setSending(false);
      if (input.current) input.current.value = '';
    }
  }
  return <section className={'upload panel ' + (dragging ? 'dragging' : '')} aria-busy={sending}
    onDragEnter={event => {
      if (!event.dataTransfer.types.includes('Files')) return;
      event.preventDefault();
      dragDepth.current++;
      setDragging(true);
    }}
    onDragOver={event => { if (event.dataTransfer.types.includes('Files')) event.preventDefault(); }}
    onDragLeave={() => {
      dragDepth.current = Math.max(0, dragDepth.current - 1);
      if (!dragDepth.current) setDragging(false);
    }}
    onDrop={event => {event.preventDefault(); dragDepth.current = 0; setDragging(false); send(event.dataTransfer.files);}}>
    <div className="upload-icon"><Icon name="upload"/></div>
    <div className="upload-copy"><h2>{sending ? 'Uploading files…' : dragging ? 'Release to upload' : 'Drop documents here'}</h2>
      <p>PDF, JPG, PNG, TIFF, XLSX, XLS and CSV · Up to 64 MiB per file</p></div>
    <button className="primary" onClick={() => input.current.click()} disabled={sending}>
      {sending ? <span className="busy-ring" aria-hidden="true"/> : <Icon name="plus"/>}
      {sending ? 'Uploading' : 'Choose files'}
    </button>
    <input hidden ref={input} type="file" multiple aria-label="Choose documents" accept=".pdf,.jpg,.jpeg,.png,.tiff,.tif,.xlsx,.xls,.csv" onChange={event => send(event.target.files)}/>
  </section>;
}

function DocumentTable({ docs, open, searchResults = false, morphId }) {
  if (!docs.length) return <div className="empty"><Icon name={searchResults ? 'search' : 'documents'}/><p>{searchResults ? 'No documents match this search.' : 'No documents to show.'}</p></div>;
  return <div className="table-wrap"><table><thead><tr><th>Document</th><th>Status</th><th>{searchResults ? 'Match' : 'Progress'}</th><th><span className="sr-only">Open</span></th></tr></thead>
    <tbody>{docs.map(doc => <tr key={doc.id}>
      <td><button className="file" onClick={() => open(doc)}><span className="file-icon"><Icon name="logo"/></span>
        <span className={morphId === doc.id ? 'file-name morph-name' : 'file-name'}>{doc.name}</span></button></td>
      <td><Status value={doc.status}/></td>
      <td>{searchResults ? <span className="excerpt">{doc.excerpt}{doc.score !== undefined && <small> Score {doc.score}</small>}</span>
        : <div className="progress-cell"><progress max="100" value={doc.progress} aria-label={doc.name + ' progress'}/><small>{doc.progress}% · {doc.stage}</small></div>}</td>
      <td><button className="icon-button" aria-label={'Open ' + doc.name} onClick={() => open(doc)}><Icon name="arrow"/></button></td>
    </tr>)}</tbody></table></div>;
}

function SearchView({ open, notify, morphId }) {
  const [query, setQuery] = useState('');
  const [mode, setMode] = useState('keyword');
  const [results, setResults] = useState(null);
  const [busy, setBusy] = useState(false);
  async function run(event) {
    event.preventDefault();
    setBusy(true);
    try {
      const params = new URLSearchParams({ q: query.trim(), mode });
      setResults(await api('/search?' + params));
    } catch (error) {
      notify(error.message, true);
    } finally {
      setBusy(false);
    }
  }
  return <>
    <header className="heading"><h1>Search</h1><p>Find invoices by exact terms or related concepts.</p></header>
    <section className="panel">
      <form className="search-form" onSubmit={run}>
        <label className="search-field"><Icon name="search"/><input type="search" aria-label="Search documents" placeholder="Invoice number, supplier, or topic" value={query} onChange={event => setQuery(event.target.value)} maxLength={250} required/></label>
        <select aria-label="Search mode" value={mode} onChange={event => setMode(event.target.value)}><option value="keyword">Keyword</option><option value="semantic">Semantic</option></select>
        <button className="primary" disabled={busy || !query.trim()}>Search</button>
      </form>
      {results && <DocumentTable docs={results} open={open} searchResults morphId={morphId}/>}
    </section>
  </>;
}

function formatValue(value) {
  if (value == null) return '—';
  if (Array.isArray(value)) return value.map(item => Object.values(item).filter(part => part != null).join(' · ')).join('\n') || '—';
  return value;
}

function InvoiceView({ invoice, notify, onSaved, compare, guide, onGuide, spreadsheet }) {
  const [draft, setDraft] = useState(null);
  const [busy, setBusy] = useState(false);
  const [receipt, setReceipt] = useState(null);
  const editor = useRef(null);
  const focusField = useRef(null);
  const data = draft || invoice.data;
  const items = data.line_items || [];
  useEffect(() => {
    if (draft && focusField.current) {
      const target = editor.current.elements.namedItem(focusField.current);
      target?.focus();
      focusField.current = null;
    }
  }, [draft]);
  function review(issue) {
    if (fields[issue.field] && issue.field !== 'line_items') focusField.current = issue.field;
    setDraft(draft ? { ...draft } : { ...invoice.data });
    onGuide(invoice, issue.field);
  }
  function itemChange(index, field, value) {
    setDraft({ ...draft, line_items: items.map((item, i) => i === index ? { ...item, [field]: value } : item) });
  }
  async function save(event) {
    event.preventDefault();
    const changes = Object.fromEntries(Object.keys(fields).filter(key => JSON.stringify(draft[key]) !== JSON.stringify(invoice.data[key])).map(key => [key, draft[key]]));
    if (!Object.keys(changes).length) return setDraft(null);
    setBusy(true);
    try {
      const saved = await api('/invoices/' + invoice.id, { method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ revision: invoice.revision, changes }) });
      setReceipt({
        changes: Object.keys(changes).map(field => ({field, before: invoice.data[field], after: saved.data[field]})),
        cleared: invoice.issues.filter(issue => !saved.issues.some(next => next.code === issue.code && next.field === issue.field))
      });
      setDraft(null);
      await onSaved();
      notify('Correction saved. Validation updated.');
    } catch (error) {
      notify(error.message, true);
    } finally {
      setBusy(false);
    }
  }
  return <form ref={editor} onSubmit={save}>
    <div className="section-head"><div><h2>{invoice.data.invoice_number || 'Unidentified invoice'}</h2><small>{invoice.source} · {invoice.extraction_method}</small></div>
      <Status value={invoice.needs_review ? 'Needs review' : 'Checks passed'}/></div>
    {invoice.issues.length > 0 && <div className="flag-list"><h3>Validation flags</h3><ul>{invoice.issues.map((issue, index) => <li key={index}>
      <button type="button" className="review-flag" onClick={() => review(issue)}>{issue.message}</button>
    </li>)}</ul></div>}
    {guide && <section className="review-evidence" aria-label="Guided exception review">
      <h3>{fields[guide.field] || 'Invoice'} evidence</h3>
      {guide.quote ? <blockquote>{guide.quote}</blockquote> : <p>No source quote is available for this flag. Check the original before entering a value.</p>}
      {guide.page && <p>Source {guide.sourceKind} {guide.page}</p>}
      {spreadsheet && <p>Source: {invoice.source}. <button type="button" onClick={spreadsheet}>Open extracted text</button></p>}
    </section>}
    {receipt && <section className="review-evidence" aria-label="Correction result">
      <h3>Correction result</h3>
      <ul>{receipt.changes.map(({field, before, after}) => <li key={field}><strong>{fields[field]}</strong>: {formatValue(before)} → {formatValue(after)}</li>)}</ul>
      {receipt.cleared.length > 0 ? <p>Cleared flags: {receipt.cleared.map(issue => issue.message).join(' ')}</p> : <p>No flags cleared.</p>}
    </section>}
    <div className="field-grid">
      {Object.entries(fields).filter(([key]) => key !== 'line_items').map(([key, label]) => <label key={key} className="fact"><span>{label}</span>
        {draft ? <input name={key} aria-label={label} value={data[key] ?? ''} onChange={event => setDraft({ ...draft, [key]: event.target.value })}/>
        : <strong>{formatValue(data[key])}</strong>}
        {typeof invoice.evidence[key] === 'string' && <small title={invoice.evidence[key]}>{invoice.evidence[key]}</small>}
      </label>)}
    </div>
    <div className="section-head"><h3>Line items</h3>{draft && <button type="button" onClick={() => setDraft({ ...draft, line_items: [...items, Object.fromEntries(Object.keys(itemFields).map(key => [key, null]))] })}>Add line</button>}</div>
    {items.length ? <div className="table-wrap"><table><thead><tr>{Object.values(itemFields).map(label => <th key={label}>{label}</th>)}{draft && <th>Remove</th>}</tr></thead><tbody>
      {items.map((item, index) => <tr key={index}>{Object.keys(itemFields).map(key => <td key={key}>{draft ? <input aria-label={itemFields[key] + ' line ' + (index + 1)} value={item[key] ?? ''} onChange={event => itemChange(index, key, event.target.value)}/> : formatValue(item[key])}</td>)}
      {draft && <td><button type="button" onClick={() => setDraft({ ...draft, line_items: items.filter((_, i) => i !== index) })}>Remove</button></td>}</tr>)}
    </tbody></table></div> : <p className="muted">No line items extracted.</p>}
    <div className="actions">{draft ? <><button key="save" type="submit" className="primary" disabled={busy}>Save correction</button><button type="button" onClick={() => setDraft(null)}>Cancel</button></>
      : <><button key="edit" type="button" className="primary" onClick={event => { event.preventDefault(); setDraft({ ...invoice.data }); }}>Correct values</button><button type="button" onClick={() => compare(invoice)}><Icon name="compare"/> Reconcile</button></>}
    </div>
  </form>;
}

function Compare({ left, docId, docs, close, notify }) {
  const section = useRef(null);
  const [target, setTarget] = useState('');
  const [offset, setOffset] = useState(0);
  const [choices, setChoices] = useState([]);
  const [invoice, setInvoice] = useState('');
  const [result, setResult] = useState(null);
  const total = docs.find(doc => doc.id === target)?.invoice_count || 0;
  useEffect(() => { section.current?.scrollIntoView({ block: 'start' }); }, []);
  useEffect(() => {
    let active = true;
    if (target) api('/documents/' + target + '/invoices?offset=' + offset)
      .then(data => { if (active) setChoices(data); })
      .catch(error => { if (active) notify(error.message, true); });
    return () => { active = false; };
  }, [target, offset]);
  function changePage(next) {
    setOffset(next);
    setChoices([]);
    setInvoice('');
    setResult(null);
  }
  async function compare(event) {
    event.preventDefault();
    try {
      setResult(await api('/reconcile?' + new URLSearchParams({ left: left.id, right: invoice })));
    } catch (error) {
      notify(error.message, true);
    }
  }
  return <section ref={section} className="panel review-panel">
    <div className="section-head"><div><h2>Reconcile invoices</h2><small>Compare {left.data.invoice_number || 'this record'} with a second document.</small></div><button onClick={close}>Close</button></div>
    <form className="actions" onSubmit={compare}>
      <select aria-label="Comparison document" value={target} onChange={event => {setTarget(event.target.value); changePage(0);}}>
        <option value="">Choose second document</option>{docs.filter(doc => doc.id !== docId && doc.status === 'completed').map(doc => <option key={doc.id} value={doc.id}>{doc.name}</option>)}
      </select>
      <select aria-label="Comparison invoice" value={invoice} onChange={event => {setInvoice(event.target.value); setResult(null);}} disabled={!choices.length}>
        <option value="">Choose invoice</option>{choices.map(entry => <option key={entry.id} value={entry.id}>{entry.data.invoice_number || 'Unidentified'} · {entry.source}</option>)}
      </select>
      {offset > 0 && <button type="button" onClick={() => changePage(offset - 100)}>Previous 100</button>}
      {offset + 100 < total && <button type="button" onClick={() => changePage(offset + 100)}>Next 100</button>}
      <button className="primary" disabled={!invoice}>Compare</button>
    </form>
    {result && <><p className="comparison-note">{result.identity_match ? 'Supplier and invoice number match.' : 'Invoice identity is different or incomplete. Review the selected records.'}</p>
      <div className="table-wrap"><table><thead><tr><th>Field</th><th>{result.left_name}</th><th>{result.right_name}</th><th>Result</th></tr></thead>
      <tbody>{result.fields.map(fact => <tr key={fact.field}><td>{fields[fact.field]}</td><td className="preline">{formatValue(fact.left)}</td><td className="preline">{formatValue(fact.right)}</td><td><Status value={fact.status}/></td></tr>)}</tbody></table></div></>}
  </section>;
}

function Detail({ id, name, docs, notify, refresh, back }) {
  const [doc, setDoc] = useState(null);
  const [page, setPage] = useState(0);
  const [invoices, setInvoices] = useState([]);
  const [selected, setSelected] = useState(null);
  const [comparison, setComparison] = useState(null);
  const [raw, setRaw] = useState(null);
  const [run, setRun] = useState(0);
  const [section, setSection] = useState('review');
  const [guide, setGuide] = useState(null);
  const [showGuidedText, setShowGuidedText] = useState(false);
  const guidedTextHeading = useRef(null);
  useEffect(() => {
    if (showGuidedText) guidedTextHeading.current?.focus();
  }, [showGuidedText]);
  async function load() {
    const next = await api('/documents/' + id);
    setDoc(next);
    setInvoices(page ? await api('/documents/' + id + '/invoices?offset=' + page) : next.invoices);
  }
  useEffect(() => {
    let active = true;
    let timer;
    async function update() {
      try {
        const next = await api('/documents/' + id);
        const rows = page ? await api('/documents/' + id + '/invoices?offset=' + page) : next.invoices;
        if (!active) return;
        setDoc(next); setInvoices(rows);
        if (['queued', 'processing'].includes(next.status)) timer = setTimeout(update, 800);
      } catch (error) {
        if (active) notify(error.message, true);
      }
    }
    update();
    return () => { active = false; clearTimeout(timer); };
  }, [id, page, run]);
  const current = invoices.find(invoice => invoice.id === selected) || invoices[0];
  const canPreview = doc && !['.csv', '.xls', '.xlsx'].includes(doc.suffix);
  function startGuide(invoice, field) {
    const single = invoice.source.match(/^(Page|Image) (\d+)$/);
    const storedPage = invoice.evidence_pages?.[field];
    setGuide({
      id: invoice.id, field,
      quote: typeof invoice.evidence[field] === 'string' ? invoice.evidence[field] : null,
      page: canPreview ? storedPage || (single ? Number(single[2]) : null) : null,
      sourceKind: doc.suffix === '.pdf' ? 'page' : 'image',
    });
  }
  const activeGuide = guide?.id === current?.id ? guide : null;
  function show(next) {
    if (next !== section) transition(() => setSection(next));
    if (next === 'source' && !raw) readText(0);
  }
  async function readText(offset) {
    try {
      setRaw(await api('/documents/' + id + '/text?offset=' + offset));
    } catch (error) {
      notify(error.message, true);
    }
  }
  async function retry() {
    try {
      await api('/documents/' + id + '/retry', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' });
      setRun(value => value + 1);
      refresh();
    } catch (error) {
      notify(error.message, true);
    }
  }
  return <>
    <button className="back" onClick={back}><Icon name="back"/> Documents</button>
    <header className="heading detail-heading"><div><h1 className="morph-name">{doc?.name || name}</h1>
      <p>{doc ? `${doc.stage} · ${doc.invoice_count} invoice ${doc.invoice_count === 1 ? 'record' : 'records'}${doc.processing_ms !== null ? ' · ' + doc.processing_ms + ' ms' : ''}` : 'Loading document…'}</p>
    </div>{doc && <Status value={doc.status}/>}</header>
    {doc && <>
      {doc.error && <div className="notice error" role="alert">
        <span>{doc.error} {doc.can_retry === false && 'Processing attempts exhausted.'}</span>
        {doc.can_retry !== false && <button onClick={retry}>Retry processing</button>}
      </div>}
      {doc.warnings.length > 0 && <details className="notice"><summary>{doc.warnings.length} processing warnings</summary><ul>{doc.warnings.map(warning => <li key={warning}>{warning}</li>)}</ul></details>}
      <div className="detail-nav" role="group" aria-label="Document sections">
        <button aria-pressed={section === 'review'} onClick={() => show('review')}>Invoice review</button>
        {doc.status === 'completed' && <button aria-pressed={section === 'source'} onClick={() => show('source')}>Source & text</button>}
        {comparison && <button aria-pressed={section === 'compare'} onClick={() => show('compare')}>Comparison</button>}
        <button aria-pressed={section === 'history'} onClick={() => show('history')}>Processing history</button>
      </div>
      <div className="section-motion" key={section}>
      {section === 'review' && !current && <div className="panel empty"><p>{doc.status === 'failed' ? 'No invoice was extracted.' : doc.status === 'completed' ? 'No invoice records were found.' : 'Invoice review will be available after processing.'}</p></div>}
      {section === 'review' && current && <div className="review-workspace"><section className="panel review-panel">
        {(doc.invoice_count > 1) && <div className="invoice-select"><select aria-label="Invoice record" value={current.id} onChange={event => {setSelected(Number(event.target.value)); setComparison(null);}}>
          {invoices.map(invoice => <option key={invoice.id} value={invoice.id}>{invoice.data.invoice_number || 'Unidentified'} · {invoice.source}</option>)}
        </select>{page > 0 && <button onClick={() => setPage(page - 100)}>Previous 100</button>}{page + 100 < doc.invoice_count && <button onClick={() => setPage(page + 100)}>Next 100</button>}</div>}
        <InvoiceView key={current.id} invoice={current} notify={notify} onSaved={load}
          guide={activeGuide} onGuide={startGuide} spreadsheet={canPreview ? null : () => {setShowGuidedText(true); readText(0);}}
          compare={invoice => {setComparison(invoice); show('compare');}}/>
        {activeGuide && !canPreview && showGuidedText && <section className="review-evidence" aria-label="Spreadsheet source">
          <h3 ref={guidedTextHeading} tabIndex={-1}>Extracted text</h3>
          {raw && <><pre>{raw.text}</pre><div className="actions">
            {raw.offset > 0 && <button onClick={() => readText(Math.max(0, raw.offset - 50000))}>Previous page</button>}
            {raw.offset + raw.text.length < raw.total && <button onClick={() => readText(raw.offset + raw.text.length)}>Next page</button>}
          </div></>}
        </section>}
      </section>{canPreview &&
        <SourcePreview key={current.id} documentId={id} name={doc.name} invoice={current} guide={activeGuide}/>}</div>}
      {section === 'compare' && comparison && <Compare key={comparison.id} left={comparison} docId={id} docs={docs} close={() => {setComparison(null); show('review');}} notify={notify}/>}
      {section === 'source' && <div className="source-workspace">
        {canPreview && current && <SourcePreview key={current.id} documentId={id} name={doc.name} invoice={current}/>}
        <section className="panel disclosure"><h2>Extracted text</h2>
        {raw && <><pre>{raw.text}</pre><div className="actions">{raw.offset > 0 && <button onClick={() => readText(Math.max(0, raw.offset - 50000))}>Previous page</button>}{raw.offset + raw.text.length < raw.total && <button onClick={() => readText(raw.offset + raw.text.length)}>Next page</button>}</div></>}
        </section>
      </div>}
      {section === 'history' && <section className="panel disclosure"><h2>Processing history</h2>
        <ol className="history-list">{doc.history.map((entry, index) => <li key={index}><strong>{entry.event.replaceAll('_', ' ')}</strong><time dateTime={new Date(entry.happened_at * 1000).toISOString()}>{new Date(entry.happened_at * 1000).toLocaleString()}</time></li>)}</ol>
      </section>}
      </div>
    </>}
  </>;
}

function SourcePreview({ documentId, name, invoice, guide }) {
  const [page, setPage] = useState(() => Number(invoice.source.match(/\b(?:Page|Image) (\d+)/i)?.[1]) || 1);
  const [pageInput, setPageInput] = useState(null);
  const [pageCount, setPageCount] = useState(0);
  const [preview, setPreview] = useState(null);
  const [failed, setFailed] = useState(false);
  const [zoom, setZoom] = useState(false);
  const [rotation, setRotation] = useState(0);
  const [attempt, setAttempt] = useState(0);
  const [expanded, setExpanded] = useState(false);
  const [collapsed, setCollapsed] = useState(false);
  const dialog = useRef(null);
  const expandButton = useRef(null);
  useEffect(() => {
    if (guide?.page) {
      setPage(guide.page);
      setPageInput(null);
      setCollapsed(false);
    }
  }, [guide]);
  useEffect(() => {
    if (collapsed) return;
    const controller = new AbortController();
    let url;
    setFailed(false);
    setPreview(null);
    async function load() {
      try {
        const response = await fetch('/api/documents/' + documentId + '/preview/' + page + '?rotation=' + rotation, { signal: controller.signal });
        if (!response.ok) throw new Error('Preview unavailable');
        const image = await response.blob();
        if (controller.signal.aborted) return;
        url = URL.createObjectURL(image);
        setPreview(url);
        setPageCount(Number(response.headers.get('X-Page-Count')) || page);
      } catch {
        if (!controller.signal.aborted) setFailed(true);
      }
    }
    load();
    return () => { controller.abort(); if (url) URL.revokeObjectURL(url); };
  }, [documentId, page, rotation, attempt, collapsed]);

  function goTo(next) {
    if (Number.isInteger(next) && next >= 1 && next <= pageCount) setPage(next);
    setPageInput(null);
  }

  function handleKeys(event) {
    if (!['ArrowLeft', 'ArrowRight'].includes(event.key) || event.target.matches('input, textarea')) return;
    event.preventDefault();
    goTo(page + (event.key === 'ArrowRight' ? 1 : -1));
  }

  function openViewer() {
    dialog.current.showModal();
    setExpanded(true);
  }

  const viewer = <>
    <div className="source-toolbar">
      <div><h2>Source preview</h2><small>Page {page}{pageCount > 0 && ' of ' + pageCount}</small></div>
      <div className="viewer-controls">
        <button type="button" aria-pressed={zoom} onClick={() => setZoom(value => !value)}>{zoom ? 'Fit' : 'Zoom'}</button>
        <button type="button" onClick={() => setRotation(value => (value + 90) % 360)}>Rotate</button>
        {!expanded && <button ref={expandButton} type="button" onClick={openViewer}>Expand</button>}
        {!expanded && <button type="button" className="fold-preview" aria-label="Collapse media preview" aria-expanded="true" onClick={() => setCollapsed(true)}><Icon name="chevron"/></button>}
      </div>
    </div>
    <div className={'source-canvas' + (zoom ? ' zoomed' : '')} tabIndex={0} aria-label="Document page">
      {preview ? <img src={preview} alt={'Original document, page ' + page}/> :
        <div className="preview-message" role="status">
          <p>{failed ? 'This page could not be rendered.' : 'Rendering page…'}</p>
          {failed && <button type="button" onClick={() => setAttempt(value => value + 1)}>Retry preview</button>}
        </div>}
    </div>
    <div className="source-pagination">
      <button type="button" disabled={page <= 1} onClick={() => goTo(page - 1)}>Previous</button>
      <form className="page-jump" onSubmit={event => { event.preventDefault(); goTo(Number(pageInput ?? page)); }}>
        <input type="number" aria-label="Go to page" min="1" max={pageCount || 1}
          disabled={!pageCount} value={pageInput ?? page}
          onChange={event => setPageInput(event.target.value)} />
        <button type="submit" disabled={!pageCount}>Go</button>
      </form>
      <button type="button" disabled={page >= pageCount} onClick={() => goTo(page + 1)}>Next</button>
    </div>
  </>;

  return <section className="panel source-panel" aria-label="Source preview">
    {collapsed ? <button type="button" className="preview-summary" aria-expanded="false" onClick={() => setCollapsed(false)}>
      <Icon name="logo"/><span>Source preview</span><small>Page {page}</small><Icon name="chevron"/>
    </button> : !expanded && viewer}
    <dialog ref={dialog} className="document-viewer" aria-label="Expanded source viewer" onKeyDown={handleKeys}
      onClose={() => { setExpanded(false); requestAnimationFrame(() => expandButton.current?.focus()); }}>
      {expanded && <>
        <header className="viewer-header">
          <div><small>Original document</small><h2>{name}</h2></div>
          <button type="button" className="viewer-close" onClick={() => dialog.current.close()} autoFocus>Close viewer</button>
        </header>
        <div className="viewer-layout">
          <div className="viewer-renderer">{viewer}</div>
          <section className="viewer-evidence" aria-label="Extracted invoice fields">
            <h3>{invoice.data.invoice_number || 'Extracted invoice fields'}</h3>
            <dl>{Object.entries(fields).filter(([key]) => key !== 'line_items').map(([key, label]) => (
              <div key={key}><dt>{label}</dt><dd>{formatValue(invoice.data[key])}</dd>
                {typeof invoice.evidence[key] === 'string' && <small>{invoice.evidence[key]}</small>}
              </div>
            ))}</dl>
          </section>
        </div>
      </>}
    </dialog>
  </section>;
}

function App() {
  const [view, setView] = useState('documents');
  const [selected, setSelected] = useState(null);
  const [morphId, setMorphId] = useState(null);
  const [docs, setDocs] = useState([]);
  const [notice, setNotice] = useState(null);
  const [filter, setFilter] = useState('');
  const [offline, setOffline] = useState(false);
  const [sidebarCollapsed, setSidebarCollapsed] = useState(() => localStorage.getItem('ledger-sidebar') === 'collapsed');
  function toggleSidebar() {
    const next = !sidebarCollapsed;
    setSidebarCollapsed(next);
    localStorage.setItem('ledger-sidebar', next ? 'collapsed' : 'expanded');
  }
  async function refresh() {
    try {
      setDocs(await api('/documents?limit=200'));
      setOffline(false);
    } catch {
      setOffline(true);
    }
  }
  useEffect(() => {
    refresh();
    const timer = setInterval(refresh, 1500);
    return () => clearInterval(timer);
  }, []);
  function notify(message, error = false) { setNotice({ message, error }); }
  function navigate(tab) {
    if (view === tab && !selected) return;
    transition(() => { setSelected(null); setView(tab); setNotice(null); });
  }
  function open(doc) {
    flushSync(() => setMorphId(doc.id));
    transition(() => { setSelected(doc); setNotice(null); });
  }
  const active = docs.filter(doc => doc.status === 'queued' || doc.status === 'processing').length;
  return <div className={'layout' + (sidebarCollapsed ? ' sidebar-collapsed' : '')}>
    <aside><div className="sidebar-header">
      <div className="brand"><div className="brand-mark"><Icon name="logo"/></div><span className="sidebar-label">Ledger Review</span></div>
    </div>
      <button className="sidebar-toggle" type="button" aria-label={sidebarCollapsed ? 'Expand sidebar' : 'Collapse sidebar'}
        aria-expanded={!sidebarCollapsed} aria-controls="workspace-navigation" title={sidebarCollapsed ? 'Expand sidebar' : 'Collapse sidebar'}
        onClick={toggleSidebar}><Icon name="sidebar"/></button>
      <nav id="workspace-navigation" aria-label="Workspace">
        <button aria-label="Documents" title="Documents" aria-current={view === 'documents' ? 'page' : undefined} className={view === 'documents' ? 'active' : ''} onClick={() => navigate('documents')}><Icon name="documents"/><span className="sidebar-label">Documents</span></button>
        <button aria-label="Search" title="Search" aria-current={view === 'search' ? 'page' : undefined} className={view === 'search' ? 'active' : ''} onClick={() => navigate('search')}><Icon name="search"/><span className="sidebar-label">Search</span></button>
      </nav>
      <div className="sidebar-foot" title={offline ? 'API unavailable' : 'Workspace connected'}><i className={offline ? 'off' : ''}/><span className="sidebar-label">{offline ? 'API unavailable' : 'Workspace connected'}</span></div>
    </aside>
    <main>
      {notice && <div className={'notice ' + (notice.error ? 'error' : '')} role={notice.error ? 'alert' : 'status'}>{notice.message}<button aria-label="Dismiss message" onClick={() => setNotice(null)}>×</button></div>}
      {selected ? <Detail key={selected.id} id={selected.id} name={selected.name} docs={docs} notify={notify} refresh={refresh} back={() => navigate('documents')}/>
      : view === 'search' ? <SearchView open={open} notify={notify} morphId={morphId}/>
      : <>
        <header className="heading workspace-heading">
          <div><h1>Documents</h1><p>Upload invoices, review source evidence, and resolve discrepancies.</p></div>
          <a href="/docs">API documentation</a>
        </header>
        {offline && <p className="notice error" role="alert">The workspace is offline. Previously listed documents may be out of date.</p>}
        <section className="summary" aria-label="Job counts">
          {[
            ['Recent documents', docs.length, 'documents', ''],
            ['In progress', active, 'clock', 'active'],
            ['Completed', docs.filter(doc => doc.status === 'completed').length, 'check', 'completed'],
            ['Failed', docs.filter(doc => doc.status === 'failed').length, 'alert', 'failed']
          ].map(([label, count, icon, status]) => <button type="button" className={'panel metric metric-' + icon} key={label}
            aria-pressed={filter === status} onClick={() => setFilter(status)}>
            <span className="metric-icon"><Icon name={icon}/></span><span>{label}</span><strong>{count}</strong>
          </button>)}
        </section>
        <Upload onUpload={refresh} notify={notify}/>
        <section className="panel"><div className="section-head activity"><h2>Recent uploads</h2>
          <select aria-label="Filter job status" value={filter} onChange={event => setFilter(event.target.value)}><option value="">All statuses</option><option value="active">In progress</option>{['queued', 'processing', 'completed', 'failed'].map(status => <option key={status} value={status}>{status}</option>)}</select>
        </div><DocumentTable key={filter} morphId={morphId} docs={docs.filter(doc => !filter || (filter === 'active' ? ['queued', 'processing'].includes(doc.status) : doc.status === filter))} open={open}/></section>
      </>}
    </main>
  </div>;
}

createRoot(document.getElementById('root')).render(<App/>);

import React, { useEffect, useState } from 'react'
import { createRoot } from 'react-dom/client'
import { ArrowDownToLine, ArrowRight, Database, GitCompareArrows, ListChecks, BarChart3, Menu, Workflow } from 'lucide-react'
import './styles.css'

const initialInput = { mode: 'file', delimiter: ',', connection: '', sql: '', max_rows: 0, password: '' }
const initialRules = {
  r_keys: [], r_ignore: [], r_agg: [], r_group: [], r_trim: true, r_empty: true,
  r_case: false, r_tol: 0, r_fast: false, r_matched: false,
  r_nulltok: 'NULL, None, NaN, N/A, #N/A', r_markers: 'N/A, NA, NULL, None, -, -999, 1900-01-01',
  r_cnt_abs: 0, r_cnt_pct: 0,
}
const ports = { PostgreSQL: 5432, 'SQL Server': 1433, MySQL: 3306, SQLite: 0 }
const blankConnection = { database_type: 'PostgreSQL', host: '', port: 5432, database: '', username: '', password: '', remember: false }
const pages = [
  { id: 'connections', name: 'Connections', icon: Database, description: 'Manage database connections for source and target queries.' },
  { id: 'inputs', name: 'Source and target', icon: GitCompareArrows, description: 'Choose the legacy and migrated data to reconcile.' },
  { id: 'rules', name: 'Comparison rules', icon: ListChecks, description: 'Choose how records are matched and which differences matter.' },
  { id: 'results', name: 'Results and reports', icon: BarChart3, description: 'Review discrepancies and download reconciliation evidence.' },
]

async function api(path, options = {}) {
  const response = await fetch('/api' + path, options)
  if (!response.ok) {
    const { detail } = await response.json()
    throw new Error(typeof detail === 'string' ? detail : 'Check the fields and try again.')
  }
  return response.json()
}

function send(path, method, data) {
  return api(path, data instanceof FormData ? { method, body: data } : {
    method, headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(data),
  })
}

function Field({ label, children }) {
  return <label className="field"><span>{label}</span>{children}</label>
}

function Select({ options, empty, ...props }) {
  return <select {...props}>
    {empty && <option value="">{empty}</option>}
    {options.map(value => <option key={value}>{value}</option>)}
  </select>
}

function Table({ table, highlight = false }) {
  if (!table?.columns.length || !table.rows.length) return <p className="muted">No rows to display.</p>
  const statusIndex = table.columns.indexOf('status')
  const mismatchIndex = table.columns.indexOf('mismatched_columns')
  return <>
    <div className="table-wrap" tabIndex="0" aria-label="Data table">
      <table>
        <thead><tr>{table.columns.map((column, i) => <th key={i}>{column}</th>)}</tr></thead>
        <tbody>{table.rows.map((row, i) => {
          const status = row[statusIndex]
          const bad = String(row[mismatchIndex] ?? '').split(',').map(value => value.trim())
          return <tr key={i}>{row.map((value, j) => {
            const column = String(table.columns[j])
            const paired = /_(source|target)$/.test(column)
            const className = value === 'FAIL' || value === 'MISMATCH' ||
              (highlight && (bad.includes(column.replace(/_(source|target)$/, '')) && paired || column === 'issue'))
              ? 'difference' : value === 'WARN' || (paired && ['MISSING_IN_TARGET', 'EXTRA_IN_TARGET'].includes(status))
                ? 'warning' : ''
            return <td key={j} className={className}>{value === null ? 'NULL' : typeof value === 'object' ? JSON.stringify(value) : String(value)}</td>
          })}</tr>
        })}</tbody>
      </table>
    </div>
    {table.total > table.rows.length && <p className="muted">Showing {table.rows.length.toLocaleString()} of {table.total.toLocaleString()} rows.</p>}
  </>
}

function Connections({ profiles, refresh, perform }) {
  const [name, setName] = useState('')
  const [selected, setSelected] = useState('')
  const [form, setForm] = useState(blankConnection)
  const update = (key, value) => setForm(previous => ({ ...previous, [key]: value }))
  function choose(value) {
    setSelected(value)
    setName(value)
    setForm(value ? { ...blankConnection, ...profiles.connections[value] } : blankConnection)
  }
  function save(test) {
    perform(async () => {
      const normalized = name.trim()
      if (!normalized) throw new Error('Enter a connection name.')
      await send('/connections/' + encodeURIComponent(normalized) + (test ? '?test=true' : ''), 'POST', form)
      if (!test) {
        await refresh()
        setSelected(normalized)
        update('password', '')
      }
      return test ? 'Connection succeeded.' : 'Connection saved.'
    })
  }
  return <section className="card">
    <h2>Database connections</h2>
    <div className="form-grid">
      <Field label="Saved connection"><Select options={Object.keys(profiles.connections)} empty="New connection" value={selected} onChange={e => choose(e.target.value)} /></Field>
      <Field label="Connection name"><input value={name} onChange={e => setName(e.target.value)} /></Field>
      <Field label="Database type"><Select options={Object.keys(ports)} value={form.database_type} onChange={e => setForm({ ...form, database_type: e.target.value, port: ports[e.target.value] })} /></Field>
      <Field label={form.database_type === 'SQLite' ? 'SQLite file path' : 'Database name'}><input value={form.database} onChange={e => update('database', e.target.value)} /></Field>
      {form.database_type !== 'SQLite' && <>
        <Field label="Host"><input value={form.host} onChange={e => update('host', e.target.value)} /></Field>
        <Field label="Port"><input type="number" min="0" max="65535" value={form.port} onChange={e => update('port', Number(e.target.value))} /></Field>
        <Field label="Username"><input value={form.username} onChange={e => update('username', e.target.value)} /></Field>
        <Field label="Password"><input type="password" value={form.password} onChange={e => update('password', e.target.value)} /></Field>
        <label className="check"><input type="checkbox" checked={form.remember} onChange={e => update('remember', e.target.checked)} /> Remember password on this machine</label>
      </>}
    </div>
    <div className="actions">
      <button className="primary" onClick={() => save(false)}>Save connection</button>
      <button onClick={() => save(true)}>Test connection</button>
      {selected && <button onClick={() => perform(async () => {
        await api('/connections/' + encodeURIComponent(selected), { method: 'DELETE' })
        await refresh()
        choose('')
        return 'Connection deleted.'
      })}>Delete connection</button>}
    </div>
  </section>
}

function Side({ title, side, value, onChange, profiles, refresh, perform }) {
  const [queryName, setQueryName] = useState('')
  const update = (key, next) => onChange({ ...value, [key]: next })
  return <section className="card">
    <h2>{title}</h2>
    <div className="segments" aria-label={title + ' input type'}>
      {[['file', 'File upload'], ['sql', 'Database query']].map(([mode, label]) =>
        <button key={mode} aria-pressed={value.mode === mode} onClick={() => update('mode', mode)}>{label}</button>)}
    </div>
    {value.mode === 'file' ? <>
      <Field label={side + ' file'}><input type="file" accept=".csv,.txt,.tsv,.xlsx,.xls,.parquet" onChange={e => update('file', e.target.files[0])} /></Field>
      {value.file && <p className="muted">{value.file.name}</p>}
      <Field label="CSV delimiter"><input maxLength={3} value={value.delimiter} onChange={e => update('delimiter', e.target.value)} /></Field>
    </> : <>
      <Field label="Connection"><Select empty="Choose a connection" options={Object.keys(profiles.connections)} value={value.connection} onChange={e => onChange({ ...value, connection: e.target.value, password: '' })} /></Field>
      {value.connection && profiles.connections[value.connection]?.database_type !== 'SQLite' &&
        <Field label="Password override"><input type="password" value={value.password} onChange={e => update('password', e.target.value)} /></Field>}
      <Field label="Saved query"><Select empty="Choose a saved query" options={Object.keys(profiles.queries)} onChange={e => update('sql', profiles.queries[e.target.value] ?? '')} /></Field>
      <Field label="SQL query"><textarea rows="5" value={value.sql} placeholder="SELECT * FROM table_name" onChange={e => update('sql', e.target.value)} /></Field>
      <Field label="Max rows (0 = all)"><input type="number" min="0" value={value.max_rows} onChange={e => update('max_rows', Number(e.target.value))} /></Field>
      <div className="actions">
        <input aria-label={side + ' saved query name'} placeholder="Save query as" value={queryName} onChange={e => setQueryName(e.target.value)} />
        <button disabled={!queryName.trim() || !value.sql.trim()} onClick={() => perform(async () => {
          const data = new FormData()
          data.set('sql', value.sql)
          await send('/queries/' + encodeURIComponent(queryName.trim()), 'PUT', data)
          await refresh()
          return 'Query saved.'
        })}>Save query</button>
      </div>
    </>}
  </section>
}

function Rules({ rules, setRules, preview, profiles, refresh, perform, compare }) {
  const [saveName, setSaveName] = useState('')
  const all = [...new Set([...preview.source.columns, ...preview.target.columns].map(c => String(c).trim().toLowerCase()))].sort()
  const targets = preview.target.columns.map(c => String(c).trim().toLowerCase())
  const common = [...new Set(preview.source.columns.map(c => String(c).trim().toLowerCase()).filter(c => targets.includes(c)))]
  const update = (key, value) => setRules(previous => ({ ...previous, [key]: value }))
  return <section className="card">
    <h2>Match and validate records</h2>
    <Field label="Saved rule set"><Select options={Object.keys(profiles.rules)} empty="Default rules" onChange={e => {
      const next = { ...initialRules, ...profiles.rules[e.target.value] }
      for (const key of ['r_keys', 'r_ignore', 'r_agg', 'r_group']) {
        const available = key === 'r_ignore' ? all : common
        next[key] = next[key].filter(column => available.includes(column))
      }
      setRules(next)
    }} /></Field>
    <div className="form-grid">
      {[
        ['r_keys', 'Key columns (empty compares whole rows)'], ['r_ignore', 'Ignore columns'],
        ['r_agg', 'Aggregation columns (empty uses numeric columns)'], ['r_group', 'Group row counts by'],
      ].map(([key, label]) => <Field key={key} label={label}>
        <Select multiple size="4" options={key === 'r_ignore' ? all : common} value={rules[key]}
          onChange={e => update(key, Array.from(e.target.selectedOptions, item => item.value))} />
      </Field>)}
    </div>
    <p className="muted">Use Ctrl or Command to select multiple columns.</p>
    <div className="form-grid">
      {[
        ['r_trim', 'Trim whitespace'], ['r_empty', 'Treat empty text as NULL'], ['r_case', 'Ignore case'],
        ['r_fast', 'Full data validation only'], ['r_matched', 'Include matched rows'],
      ].map(([key, label]) => <label key={key} className="check"><input type="checkbox" checked={rules[key]} onChange={e => update(key, e.target.checked)} />{label}</label>)}
    </div>
    <div className="form-grid">
      {[
        ['r_tol', 'Numeric tolerance', 'any'], ['r_cnt_abs', 'Row-count tolerance (rows)', '1'],
        ['r_cnt_pct', 'Row-count tolerance (%)', 'any'],
      ].map(([key, label, step]) => <Field key={key} label={label}>
        <input type="number" min="0" step={step} value={rules[key]} onChange={e => update(key, Number(e.target.value))} />
      </Field>)}
      <Field label="Values treated as NULL"><input value={rules.r_nulltok} onChange={e => update('r_nulltok', e.target.value)} /></Field>
      <Field label="Missing-value markers"><input value={rules.r_markers} onChange={e => update('r_markers', e.target.value)} /></Field>
    </div>
    <div className="actions">
      <button className="primary" onClick={compare}>Run comparison <ArrowRight size={16} /></button>
      <input aria-label="Saved rule name" placeholder="Save rules as" value={saveName} onChange={e => setSaveName(e.target.value)} />
      <button disabled={!saveName.trim()} onClick={() => perform(async () => {
        await send('/rules/' + encodeURIComponent(saveName.trim()), 'PUT', rules)
        await refresh()
        return 'Rule set saved.'
      })}>Save rules</button>
    </div>
  </section>
}

function Results({ result }) {
  const [key, setKey] = useState('checks')
  const [status, setStatus] = useState('')
  const [loaded, setLoaded] = useState(null)
  const [error, setError] = useState('')
  const query = key === 'full' && status ? '?status=' + encodeURIComponent(status) : ''
  useEffect(() => {
    const controller = new AbortController()
    api('/results/' + key + query, { signal: controller.signal })
      .then(table => { setLoaded({ key, query, table }); setError('') })
      .catch(err => { if (err.name !== 'AbortError') setError(err.message) })
    return () => controller.abort()
  }, [result, key, query])
  const counts = result.counts.full_counts
  const metrics = [
    ['Source rows', result.counts.source_rows], ['Target rows', result.counts.target_rows],
    ['Missing in target', counts.MISSING_IN_TARGET], ['Extra in target', counts.EXTRA_IN_TARGET],
    ['Mismatched cells', result.counts.total_mismatch_cells],
  ]
  const selected = result.tables.find(item => item.key === key)
  return <>
    <div className={'notice ' + (result.passed ? 'success' : 'error')}>
      <strong>{result.passed ? 'PASS' : 'FAIL'}</strong> · {result.mode} · {result.seconds}s
    </div>
    <div className="metrics">{metrics.map(([label, value]) => <div className="card metric" key={label}><span>{label}</span><strong>{(value ?? 0).toLocaleString()}</strong></div>)}</div>
    <section className="card">
      <h2>Download reports</h2>
      <div className="actions">
        {Object.entries({ xlsx: 'Excel', csv: 'CSV ZIP', json: 'JSON summary', html: 'HTML evidence' }).map(([kind, label]) =>
          <a key={kind} className="button" download href={'/api/reports/' + kind}><ArrowDownToLine size={16} />{label}</a>)}
      </div>
    </section>
    <section className="card">
      <div className="form-grid">
        <Field label="Result table"><select value={key} onChange={e => { setError(''); setKey(e.target.value) }}>
          {result.tables.map(item => <option key={item.key} value={item.key}>{item.name}{item.total === null ? '' : ' (' + item.total.toLocaleString() + ')'}</option>)}
        </select></Field>
        {key === 'full' && <Field label="Status"><Select empty="All statuses" options={Object.keys(counts)} value={status} onChange={e => { setError(''); setStatus(e.target.value) }} /></Field>}
      </div>
      <h2>{selected.name}</h2>
      {error ? <p role="alert">{error}</p> : loaded?.key === key && loaded.query === query
        ? <Table table={loaded.table} highlight={['full', 'mismatches'].includes(key)} />
        : <p role="status">Loading results…</p>}
    </section>
  </>
}

function App() {
  const [page, setPage] = useState('inputs')
  const [menu, setMenu] = useState(false)
  const [profiles, setProfiles] = useState({ connections: {}, queries: {}, rules: {} })
  const [source, setSource] = useState(initialInput)
  const [target, setTarget] = useState(initialInput)
  const [preview, setPreview] = useState(null)
  const [rules, setRules] = useState(initialRules)
  const [result, setResult] = useState(null)
  const [notice, setNotice] = useState(null)
  const [busy, setBusy] = useState(false)
  const current = pages.find(item => item.id === page)
  const refresh = () => api('/profiles').then(setProfiles)
  useEffect(() => { refresh().catch(error => setNotice({ error: true, text: error.message })) }, [])

  function navigate(id) {
    setPage(id)
    setMenu(false)
    setNotice(null)
    window.scrollTo(0, 0)
  }
  async function perform(work) {
    setBusy(true)
    setNotice(null)
    try {
      const message = await work()
      if (message) setNotice({ text: message })
    } catch (error) {
      setNotice({ error: true, text: error.message })
    } finally {
      setBusy(false)
    }
  }
  function loadData() {
    perform(async () => {
      const form = new FormData()
      for (const [name, input] of [['source', source], ['target', target]]) {
        const { mode, file, delimiter, connection, sql, max_rows, password } = input
        if (mode === 'file' && !file) throw new Error('Choose a ' + name + ' file.')
        if (mode === 'sql' && (!connection || !sql.trim())) throw new Error('Choose a connection and enter a query for the ' + name + '.')
        form.set(name, JSON.stringify(mode === 'file' ? { delimiter: delimiter || ',' } : { connection, sql, max_rows, password }))
        if (mode === 'file') form.set(name + '_file', file)
      }
      const loaded = await send('/inputs', 'POST', form)
      const targetColumns = loaded.target.columns.map(c => String(c).trim().toLowerCase())
      const keys = loaded.source.columns.map(c => String(c).trim().toLowerCase())
        .filter(c => ['id', 'pk'].includes(c) && targetColumns.includes(c)).slice(0, 1)
      setPreview(loaded)
      setRules({ ...initialRules, r_keys: keys })
      setResult(null)
      return 'Source and target loaded.'
    })
  }

  return <div className="workspace">
    <aside className={menu ? 'sidebar open' : 'sidebar'}>
      <div className="brand"><div className="brand-icon"><Workflow size={23} /></div><div><strong>Equaliser</strong><span>Data migration testing</span></div></div>
      <div className="workspace-label"><span>WORKSPACE</span><strong>Migration reconciliation</strong></div>
      <nav aria-label="Workspace">
        <p>RECONCILIATION</p>
        {pages.map(({ id, name, icon: Icon }) =>
          <button key={id} aria-current={id === page ? 'page' : undefined} onClick={() => navigate(id)}><Icon size={18} /> {name}</button>)}
      </nav>
    </aside>
    <div className="body">
      <header><button className="menu" aria-label="Toggle navigation" aria-expanded={menu} onClick={() => setMenu(!menu)}><Menu size={20} /></button>
        <span>Migration workspace</span><span aria-hidden="true">/</span><strong>{current.name}</strong>
      </header>
      <main>
        <div className="page-heading"><h1>{current.name}</h1><p>{current.description}</p></div>
        {notice && <div className={'notice ' + (notice.error ? 'error' : 'success')} role={notice.error ? 'alert' : 'status'}>{notice.text}</div>}
        {busy && <p role="status" className="muted">Working…</p>}
        <fieldset disabled={busy}>
          {page === 'connections' && <Connections {...{ profiles, refresh, perform }} />}
          {page === 'inputs' && <>
            <div className="two-up">
              <Side title="Source (legacy)" side="Source" value={source} onChange={setSource} {...{ profiles, refresh, perform }} />
              <Side title="Target (migrated)" side="Target" value={target} onChange={setTarget} {...{ profiles, refresh, perform }} />
            </div>
            <div className="actions">
              <button className="primary" onClick={loadData}>Load data</button>
              {preview && <button onClick={() => navigate('rules')}>Comparison rules <ArrowRight size={16} /></button>}
            </div>
            {preview && <div className="two-up previews">{['source', 'target'].map(side =>
              <section className="card" key={side}><h2>{side === 'source' ? 'Source' : 'Target'} preview</h2><p className="muted">{preview[side].total.toLocaleString()} rows</p><Table table={preview[side]} /></section>)}</div>}
          </>}
          {page === 'rules' && (preview
            ? <Rules {...{ rules, setRules, preview, profiles, refresh, perform }} compare={() => perform(async () => {
              setResult(await send('/compare', 'POST', rules))
              navigate('results')
            })} />
            : <section className="card empty"><h2>Load source and target data first</h2><button onClick={() => navigate('inputs')}>Go to source and target <ArrowRight size={16} /></button></section>)}
          {page === 'results' && (result ? <Results result={result} /> : <section className="card empty">
            <h2>No comparison results yet</h2><button onClick={() => navigate(preview ? 'rules' : 'inputs')}>{preview ? 'Go to comparison rules' : 'Go to source and target'} <ArrowRight size={16} /></button>
          </section>)}
        </fieldset>
      </main>
    </div>
  </div>
}

createRoot(document.getElementById('root')).render(<App />)

import { useCallback, useEffect, useRef, useState } from 'react'
import {
  ApiError,
  browseDatasource,
  deleteDirectory,
  deleteDocument,
  enqueueSync,
  getSyncStatus,
  listDirectories,
  listDocuments,
  registerDirectory,
  type Directory,
  type DocumentRow,
  type SyncJob,
} from '../api'

const POLL_MS = 1200

function syncSummary(job: SyncJob): string {
  switch (job.state) {
    case 'queued':
      return 'queued…'
    case 'running':
      return `running… scanned ${job.stats.scanned ?? 0}`
    case 'succeeded': {
      const indexed = job.stats.indexed ?? 0
      const deduped = job.stats.deduped ?? 0
      const unchanged = job.stats.unchanged ?? 0
      if (indexed === 0 && deduped === 0) return `nothing new to sync (unchanged ${unchanged})`
      return `finished — indexed ${indexed}, deduped ${deduped}, unchanged ${unchanged}`
    }
    case 'partial':
      return `finished with ${job.error_count} error(s)`
    case 'failed':
      return 'sync failed'
    default:
      return job.state
  }
}

function DirectoryItem({ directory, onDeleted }: { directory: Directory; onDeleted: () => void }) {
  const [job, setJob] = useState<SyncJob | null>(null)
  const [jobError, setJobError] = useState<string | null>(null)
  const [expanded, setExpanded] = useState(false)
  const [documents, setDocuments] = useState<DocumentRow[]>([])
  const [docError, setDocError] = useState<string | null>(null)
  const mountedRef = useRef(true)
  const expandedRef = useRef(expanded)
  const pollingRef = useRef<number | null>(null)

  useEffect(() => {
    expandedRef.current = expanded
  }, [expanded])

  useEffect(() => {
    mountedRef.current = true
    return () => {
      mountedRef.current = false
      if (pollingRef.current !== null) window.clearTimeout(pollingRef.current)
    }
  }, [])

  const refreshDocuments = useCallback(async () => {
    try {
      const docs = await listDocuments(directory.id)
      if (mountedRef.current) setDocuments(docs)
    } catch (err) {
      if (mountedRef.current) setDocError(err instanceof ApiError ? String(err.detail) : 'failed to load documents')
    }
  }, [directory.id])

  // Reads expandedRef/mountedRef rather than closing over `expanded`, so the
  // recursive setTimeout chain always sees the current panel state instead
  // of whatever it was when polling started.
  const poll = useCallback(
    (currentJob: SyncJob) => {
      if (currentJob.state !== 'queued' && currentJob.state !== 'running') {
        if (expandedRef.current) void refreshDocuments()
        return
      }
      pollingRef.current = window.setTimeout(async () => {
        try {
          const next = await getSyncStatus(directory.id)
          if (!mountedRef.current) return
          setJob(next)
          poll(next)
        } catch {
          // transient poll failure — try again on the next tick
          if (mountedRef.current) pollingRef.current = window.setTimeout(() => poll(currentJob), POLL_MS)
        }
      }, POLL_MS)
    },
    [directory.id, refreshDocuments],
  )

  useEffect(() => {
    getSyncStatus(directory.id)
      .then((initial) => {
        if (!mountedRef.current) return
        setJob(initial)
        poll(initial)
      })
      .catch((err) => {
        if (err instanceof ApiError && err.status === 404) return // never synced yet
      })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [directory.id])

  async function handleSync() {
    setJobError(null)
    try {
      const started = await enqueueSync(directory.id)
      setJob(started)
      poll(started)
    } catch (err) {
      if (err instanceof ApiError && err.status === 409) {
        const existing = err.detail as SyncJob
        setJob(existing)
        poll(existing)
        return
      }
      setJobError(err instanceof ApiError ? String(err.detail) : 'sync failed to start')
    }
  }

  async function toggleExpand() {
    const next = !expanded
    setExpanded(next)
    if (next) await refreshDocuments()
  }

  async function handleRemove(documentId: string) {
    setDocError(null)
    try {
      await deleteDocument(documentId)
      await refreshDocuments()
    } catch (err) {
      setDocError(err instanceof ApiError ? String(err.detail) : 'remove failed')
    }
  }

  async function handleDeleteDirectory() {
    try {
      await deleteDirectory(directory.id)
      onDeleted()
    } catch (err) {
      setJobError(err instanceof ApiError ? String(err.detail) : 'delete failed')
    }
  }

  const syncing = job !== null && (job.state === 'queued' || job.state === 'running')

  return (
    <div className="directory">
      <div className="directory-header">
        <span className="prefix">{directory.prefix}</span>
        <button onClick={handleSync} disabled={syncing}>
          {syncing ? 'Syncing…' : 'Sync'}
        </button>
        <button onClick={toggleExpand}>{expanded ? 'Hide files' : 'Show files'}</button>
        <button onClick={handleDeleteDirectory} className="danger">
          Delete
        </button>
      </div>
      {job && <div className="sync-status">{syncSummary(job)}</div>}
      {jobError && <div className="error">{jobError}</div>}
      {expanded && (
        <ul className="documents">
          {documents.length === 0 && <li className="empty">No documents yet — sync first.</li>}
          {documents.map((doc) => (
            <li key={doc.id}>
              <span className="filename">{doc.filename}</span>
              <span className="badge">{doc.state}</span>
              {doc.error && <span className="error">{doc.error}</span>}
              <button onClick={() => handleRemove(doc.id)} className="danger">
                Remove
              </button>
            </li>
          ))}
          {docError && <li className="error">{docError}</li>}
        </ul>
      )}
    </div>
  )
}

export function Directories({ datasourceId }: { datasourceId: string }) {
  const [directories, setDirectories] = useState<Directory[]>([])
  const [prefix, setPrefix] = useState('')
  const [browseResults, setBrowseResults] = useState<string[] | null>(null)
  const [error, setError] = useState<string | null>(null)

  const refreshDirectories = useCallback(async () => {
    try {
      setDirectories(await listDirectories(datasourceId))
    } catch (err) {
      setError(err instanceof ApiError ? String(err.detail) : 'failed to load directories')
    }
  }, [datasourceId])

  useEffect(() => {
    setPrefix('')
    setBrowseResults(null)
    void refreshDirectories()
  }, [refreshDirectories])

  async function handleBrowse() {
    setError(null)
    try {
      setBrowseResults(await browseDatasource(datasourceId, prefix))
    } catch (err) {
      setError(err instanceof ApiError ? String(err.detail) : 'browse failed')
    }
  }

  async function handleRegister(prefixToRegister: string) {
    setError(null)
    try {
      await registerDirectory(datasourceId, prefixToRegister)
      setBrowseResults(null)
      await refreshDirectories()
    } catch (err) {
      setError(err instanceof ApiError ? String(err.detail) : 'register failed')
    }
  }

  return (
    <div className="directories">
      <h3>Directories</h3>
      <div className="browse-row">
        <input
          value={prefix}
          onChange={(e) => setPrefix(e.target.value)}
          placeholder="prefix, e.g. alice/contracts/"
        />
        <button onClick={handleBrowse}>Browse</button>
        <button onClick={() => handleRegister(prefix)} disabled={!prefix}>
          Register
        </button>
      </div>
      {browseResults && (
        <ul className="browse-results">
          {browseResults.length === 0 && <li className="empty">No sub-prefixes here.</li>}
          {browseResults.map((p) => (
            <li key={p}>
              <span>{p}</span>
              <button onClick={() => handleRegister(p)}>Register</button>
            </li>
          ))}
        </ul>
      )}
      {error && <div className="error">{error}</div>}
      <div className="directory-list">
        {directories.length === 0 && <p className="empty">No directories registered yet.</p>}
        {directories.map((d) => (
          <DirectoryItem key={d.id} directory={d} onDeleted={refreshDirectories} />
        ))}
      </div>
    </div>
  )
}

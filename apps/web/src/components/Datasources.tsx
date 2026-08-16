import { useEffect, useState } from 'react'
import { ApiError, createDatasource, listDatasources, type Datasource, type S3Config } from '../api'
import { Directories } from './Directories'

const LOCALSTACK_DEFAULTS: S3Config = {
  endpoint_url: 'http://localstack:4566',
  bucket_name: 'nimbus-dev',
  access_key_id: 'test',
  secret_access_key: 'test',
  region_name: 'us-east-1',
}

export function Datasources() {
  const [datasources, setDatasources] = useState<Datasource[]>([])
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [showForm, setShowForm] = useState(false)
  const [name, setName] = useState('my-s3')
  const [config, setConfig] = useState<S3Config>(LOCALSTACK_DEFAULTS)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    listDatasources()
      .then((rows) => {
        setDatasources(rows)
        if (rows.length > 0) setSelectedId((current) => current ?? rows[0].id)
      })
      .catch((err) => setError(err instanceof ApiError ? String(err.detail) : 'failed to load datasources'))
  }, [])

  async function handleCreate() {
    setError(null)
    try {
      const created = await createDatasource(name, config)
      setDatasources((rows) => [...rows, created])
      setSelectedId(created.id)
      setShowForm(false)
    } catch (err) {
      setError(err instanceof ApiError ? String(err.detail) : 'connect failed')
    }
  }

  return (
    <div className="panel datasources">
      <h2>Datasources</h2>
      <div className="datasource-list">
        {datasources.map((ds) => (
          <button
            key={ds.id}
            className={ds.id === selectedId ? 'chip selected' : 'chip'}
            onClick={() => setSelectedId(ds.id)}
          >
            {ds.name}
          </button>
        ))}
        <button className="chip add" onClick={() => setShowForm((v) => !v)}>
          + Connect
        </button>
      </div>

      {showForm && (
        <div className="connect-form">
          <label>
            Name
            <input value={name} onChange={(e) => setName(e.target.value)} />
          </label>
          <label>
            Endpoint URL
            <input value={config.endpoint_url} onChange={(e) => setConfig({ ...config, endpoint_url: e.target.value })} />
          </label>
          <label>
            Bucket
            <input value={config.bucket_name} onChange={(e) => setConfig({ ...config, bucket_name: e.target.value })} />
          </label>
          <label>
            Access key ID
            <input value={config.access_key_id} onChange={(e) => setConfig({ ...config, access_key_id: e.target.value })} />
          </label>
          <label>
            Secret access key
            <input
              type="password"
              value={config.secret_access_key}
              onChange={(e) => setConfig({ ...config, secret_access_key: e.target.value })}
            />
          </label>
          <label>
            Region
            <input value={config.region_name} onChange={(e) => setConfig({ ...config, region_name: e.target.value })} />
          </label>
          <button onClick={handleCreate}>Save</button>
        </div>
      )}

      {error && <div className="error">{error}</div>}

      {selectedId && <Directories datasourceId={selectedId} />}
    </div>
  )
}

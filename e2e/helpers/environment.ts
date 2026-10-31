export function journeyServiceUrl(port: number, path = ''): string {
  if (process.env.E2E_ISOLATED !== '1') return `http://localhost:${port}${path}`
  const urls: Record<string, unknown> = JSON.parse(process.env.E2E_SERVICE_URLS ?? '{}')
  const base = urls[String(port)]
  if (typeof base !== 'string') throw new Error(`Isolated journey service URL missing for port ${port}.`)
  const url = new URL(base)
  if (url.hostname !== '127.0.0.1' || url.protocol !== 'http:')
    throw new Error('Isolated journey services must use HTTP loopback addresses.')
  return `${url.origin}${path}`
}

import { resolve } from 'node:path'

export function isolatedModel(source, root, credentials) {
  const services = structuredClone(source.services)
  const servicePorts = {}
  const downstream = Object.fromEntries(Object.keys(services).filter(name => name.endsWith('-service'))
    .map(name => [name.replace(/-/g, '_').toUpperCase() + '_URL', `http://${name}:5000`]))
  const common = {
    ...downstream, DATABASE_URL: `postgresql://postgres:${credentials.database}@database:5432/journeys`,
    SUPABASE_URL: 'http://supabase', SUPABASE_ANON_KEY: 'isolated-local-auth',
    FRONTEND_ORIGIN: credentials.frontendOrigin, INTERNAL_SERVICE_TOKEN: credentials.internal,
    RABBITMQ_URL: `amqp://journeys:${credentials.rabbit}@rabbitmq:5672/%2F`,
    VENUE_BOOKING_LEGACY_SCHEMA: 'false', VENUE_CLOSURE_DEV_MODE: 'false',
    CLOSURE_CONFIRMATION_KEY: credentials.internal,
  }
  for (const [name, service] of Object.entries(services)) {
    delete service.env_file
    delete service.restart
    if (service.build) {
      const context = typeof service.build === 'string' ? service.build : service.build.context
      service.build = { ...(typeof service.build === 'object' ? service.build : {}), context: resolve(root, context) }
    }
    const owner = service.environment?.OUTBOX_OWNER
    service.environment = { ...common, ...(owner ? { OUTBOX_OWNER: owner } : {}) }
    if (service.ports) {
      service.ports = service.ports.map(mapping => {
        const parts = String(mapping).split(':')
        servicePorts[parts.at(-2)] = name
        return { target: Number(parts.at(-1)), host_ip: '127.0.0.1', published: '0' }
      })
    }
  }
  services.rabbitmq.environment = { RABBITMQ_DEFAULT_USER: 'journeys', RABBITMQ_DEFAULT_PASS: credentials.rabbit }
  services.database = {
    image: 'postgres:17.6', environment: { POSTGRES_PASSWORD: credentials.database, POSTGRES_DB: 'journeys' },
    ports: [{ target: 5432, host_ip: '127.0.0.1', published: '0' }],
    volumes: ['journeys-database:/var/lib/postgresql/data',
      { type: 'bind', source: resolve(root, 'e2e', 'isolated', 'bootstrap.sql'), target: '/docker-entrypoint-initdb.d/bootstrap.sql', read_only: true }],
    healthcheck: { test: ['CMD-SHELL', 'pg_isready -h 127.0.0.1 -U postgres -d journeys'], interval: '2s', timeout: '3s', retries: 60 },
  }
  services['supabase-auth'] = {
    image: 'supabase/gotrue:v2.197.0',
    environment: {
      GOTRUE_API_HOST: '0.0.0.0', GOTRUE_API_PORT: '9999', API_EXTERNAL_URL: 'http://supabase/auth/v1',
      GOTRUE_DB_DRIVER: 'postgres',
      GOTRUE_DB_DATABASE_URL: `postgresql://supabase_auth_admin:${credentials.database}@database:5432/journeys?search_path=auth`,
      GOTRUE_SITE_URL: credentials.frontendOrigin, GOTRUE_DISABLE_SIGNUP: 'true',
      GOTRUE_JWT_SECRET: credentials.internal, GOTRUE_JWT_KEYS: JSON.stringify([credentials.signingKey]),
      GOTRUE_JWT_AUD: 'authenticated', GOTRUE_JWT_EXP: '86400',
      GOTRUE_JWT_ADMIN_ROLES: 'service_role', GOTRUE_JWT_DEFAULT_GROUP_NAME: 'authenticated',
      GOTRUE_EXTERNAL_EMAIL_ENABLED: 'true', GOTRUE_MAILER_AUTOCONFIRM: 'true',
      GOTRUE_HOOK_CUSTOM_ACCESS_TOKEN_ENABLED: 'true',
      GOTRUE_HOOK_CUSTOM_ACCESS_TOKEN_URI: 'pg-functions://postgres/public/custom_access_token_hook',
      GOTRUE_RATE_LIMIT_EMAIL_SENT: '1000', GOTRUE_RATE_LIMIT_TOKEN_REFRESH: '1000',
    },
    depends_on: { database: { condition: 'service_healthy' } },
  }
  services.supabase = {
    image: 'nginx:1.27-alpine', depends_on: ['supabase-auth'],
    ports: [{ target: 80, host_ip: '127.0.0.1', published: '0' }],
    volumes: [{ type: 'bind', source: resolve(root, 'e2e', 'isolated', 'auth-proxy.conf'), target: '/etc/nginx/nginx.conf', read_only: true }],
  }
  return { compose: { services, volumes: { ...source.volumes, 'journeys-database': {} } }, servicePorts }
}

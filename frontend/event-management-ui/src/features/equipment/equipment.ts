export const EQUIPMENT_TYPES = ['Microphone', 'LightingKit', 'Projector', 'Laptop', 'Furniture', 'Table', 'Chair', 'Speaker'] as const
export const EQUIPMENT_STATUSES = ['Available', 'Reserved', 'Unavailable'] as const

export type EquipmentType = (typeof EQUIPMENT_TYPES)[number]
export type EquipmentStatus = (typeof EQUIPMENT_STATUSES)[number]

export interface Equipment {
  id: string
  type: string
  description: string
  totalQuantity: number
  location: string
  status: string
  setupRequirements: string
}

export interface NewEquipment {
  equipmentType: string
  description: string
  totalQuantity: number
  location: string
  status: EquipmentStatus
}

const equipmentServiceUrl = () => import.meta.env.VITE_EQUIPMENT_SERVICE_URL || 'http://localhost:5002'

export async function fetchEquipment(status?: EquipmentStatus): Promise<Equipment[]> {
  const query = status ? `?status=${encodeURIComponent(status)}` : ''
  const response = await fetch(`${equipmentServiceUrl()}/equipment${query}`)
  const body = await response.json().catch(() => ({}))
  if (!response.ok) throw new Error(body.message || 'Unable to load the equipment catalogue.')
  return body.equipment as Equipment[]
}

/** DEV headers identify the switcher user; they are spoofable until real auth lands. */
export async function createEquipment(payload: NewEquipment, user: { id: string; role: string }): Promise<Equipment> {
  const response = await fetch(`${equipmentServiceUrl()}/equipment`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', 'X-Dev-User-Id': user.id, 'X-Dev-Role': user.role },
    body: JSON.stringify(payload),
  })
  const body = await response.json().catch(() => ({}))
  if (!response.ok) throw new Error(body.message || 'Unable to add this equipment.')
  return body.equipment as Equipment
}

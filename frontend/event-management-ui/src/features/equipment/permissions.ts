import type { Role } from '../../types'

/** Only Technical Support may view the equipment catalogue and add records. */
export function canManageEquipment(role: Role): boolean {
  return role === 'Technical Support'
}

export const EQUIPMENT_ACCESS_NOTICE = 'The Equipment Catalogue is visible to Technical Support staff.'

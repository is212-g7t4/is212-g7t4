const TIME_ZONE = 'Asia/Singapore'

export function getDateTile(value: string): { month: string; day: string } {
  const parsed = new Date(value)
  if (Number.isNaN(parsed.getTime())) return { month: '—', day: '—' }
  return {
    month: parsed.toLocaleString('en-SG', { timeZone: TIME_ZONE, month: 'short' }).toUpperCase(),
    day: parsed.toLocaleString('en-SG', { timeZone: TIME_ZONE, day: '2-digit' }),
  }
}

function sameDay(a: Date, b: Date): boolean {
  const format = (date: Date) => date.toLocaleDateString('en-SG', { timeZone: TIME_ZONE })
  return format(a) === format(b)
}

function weekdayDate(value: Date): string {
  return value.toLocaleString('en-SG', { timeZone: TIME_ZONE, weekday: 'short', day: 'numeric', month: 'short' })
}

function time(value: Date): string {
  return value.toLocaleString('en-SG', { timeZone: TIME_ZONE, hour: 'numeric', minute: '2-digit', hour12: true })
}

export function formatSchedule(startValue: string, endValue: string): string {
  const start = new Date(startValue)
  const end = new Date(endValue)
  if (Number.isNaN(start.getTime()) || Number.isNaN(end.getTime())) {
    return `${startValue.replace('T', ' ')} – ${endValue.replace('T', ' ')}`
  }
  if (sameDay(start, end)) {
    return `${weekdayDate(start)} · ${time(start)} – ${time(end)}`
  }
  return `${weekdayDate(start)}, ${time(start)} – ${weekdayDate(end)}, ${time(end)}`
}

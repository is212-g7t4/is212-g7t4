// Supporting infrastructure: actual Vitest ready/result events (not declaration order).
import { appendFileSync } from 'node:fs'
export default class OrderReporter {
  onTestCaseReady(test) {
    appendFileSync(process.env.SCRUM173_VITEST_EVIDENCE, JSON.stringify({ event: 'started', id: test.id, name: test.fullName }) + '\n')
  }
  onTestCaseResult(test) {
    appendFileSync(process.env.SCRUM173_VITEST_EVIDENCE, JSON.stringify({ event: 'result', id: test.id, name: test.fullName, result: test.result() }) + '\n')
  }
}

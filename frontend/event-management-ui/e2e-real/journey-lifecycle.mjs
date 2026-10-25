/** SCRUM-45 verification-only external-I/O lifecycle (no browser at import). */
export async function runBrowserJourney({ browser, run, screenshot, writeRequests, reportDiagnostic = console.error }) {
  let journeyFailed = false
  const diagnostics = []
  try {
    return await run()
  } catch (error) {
    journeyFailed = true
    try {
      await screenshot()
    } catch (error) {
      diagnostics.push({ operation: 'screenshot', error })
    }
    throw error
  } finally {
    try {
      try {
        await writeRequests()
      } catch (error) {
        diagnostics.push({ operation: 'writeRequests', error })
      }
    } finally {
      try {
        await browser.close()
      } catch (error) {
        diagnostics.push({ operation: 'close', error })
      }
    }
    for (const diagnostic of diagnostics) reportDiagnostic(diagnostic)
    if (!journeyFailed && diagnostics.length) {
      throw new AggregateError(diagnostics.map(diagnostic => diagnostic.error), 'Browser journey diagnostics/cleanup failed')
    }
  }
}

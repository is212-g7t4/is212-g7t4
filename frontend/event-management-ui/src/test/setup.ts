import '@testing-library/jest-dom/vitest'
import { afterEach } from 'vitest'
import { cleanup } from '@testing-library/react'
afterEach(cleanup)

// jsdom ships no modal API for <dialog>, so any component calling showModal()
// throws there (jsdom#3294). These stand-ins just keep `open` in sync, which
// is what the accessibility tree — and so getByRole('dialog') — reads.
if (!HTMLDialogElement.prototype.showModal) {
  HTMLDialogElement.prototype.showModal = function showModal() { this.open = true }
  HTMLDialogElement.prototype.close = function close() { this.open = false }
}
